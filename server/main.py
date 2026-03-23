# server/main.py
import asyncio
import base64
import hashlib
import json
import logging
import math
import re
import secrets
import uuid
import httpx
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Response, UploadFile, File, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict
import uvicorn
import os
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from contextlib import asynccontextmanager
from database import Base, engine, get_db
from models import DBChallenge, DBProblem, DBRateLimit, DBRecoveryCode, DBSession, DBSubmission, DBUser

logger = logging.getLogger("cmdcode")

load_dotenv()


# ---------------------------------------------------------------------------
# Rate-limit constants
# ---------------------------------------------------------------------------

SUBMIT_RATE_BASE_SECONDS = 2       # base cooldown between submissions
SUBMIT_RATE_WINDOW_SECONDS = 300   # 5-minute sliding window
SUBMIT_RATE_MAX_COOLDOWN = 120     # cap at 2 minutes

CHALLENGE_RATE_LIMIT = 10          # max challenges per username per window
CHALLENGE_RATE_WINDOW = 300        # 5-minute window

VERIFY_FAIL_LIMIT = 5             # max failed verifications per username
VERIFY_FAIL_WINDOW = 900          # 15-minute window

MAX_UPLOAD_BYTES = 1_048_576       # 1 MB file upload limit

RECOVER_RATE_LIMIT = 3             # max recovery attempts per username per hour
RECOVER_RATE_WINDOW = 3600         # 1-hour window
RECOVERY_CODE_COUNT = 8            # number of one-time recovery codes issued per generation

# In-memory IP-based registration limiter
_register_ip_counts: Dict[str, list] = defaultdict(list)
REGISTER_IP_LIMIT = 5
REGISTER_IP_WINDOW = 3600          # 1 hour


@asynccontextmanager
async def lifespan(application):
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        _sync_problems(db)
    finally:
        db.close()
    task = asyncio.create_task(_problem_reload_loop())
    yield
    task.cancel()


app = FastAPI(title="cmdcode Server", description="Your personal coding judge", lifespan=lifespan)
APP_PORT = int(os.getenv("APP_PORT", 8000))
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0:2358")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TestCase(BaseModel):
    input: str
    output: str
    hidden: bool = False

class Problem(BaseModel):
    id: int
    title: str
    description: str
    difficulty: str
    test_cases: List[TestCase]
    starter_code: Dict[str, str]

class SubmissionResponse(BaseModel):
    problem_id: int
    filename: str
    code: str
    language: str = "cpp"
    submitted_at: str
    size_bytes: int
    status: str = "received"
    passed: bool = False

class RegisterRequest(BaseModel):
    username: str
    email: str
    public_key: str

class VerifyRequest(BaseModel):
    username: str
    challenge_id: str
    signature: str

class RecoverRequest(BaseModel):
    username: str
    recovery_code: str
    new_public_key: str


# ---------------------------------------------------------------------------
# Language map
# ---------------------------------------------------------------------------

LANGUAGE_IDS = {
    ".cpp": 54,
    ".c": 52,
    ".py": 71,
    ".java": 62,
    ".js": 63,
    ".ts": 74,
    ".go": 60,
    ".rs": 73,
}


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_PROBLEMS_FILE = os.path.join(os.path.dirname(__file__), "problems.json")

# Track last-seen mtime so we only reload when the file actually changes
_problems_file_mtime: float = 0.0

# How often (seconds) to check problems.json for changes
PROBLEM_RELOAD_INTERVAL = int(os.getenv("PROBLEM_RELOAD_INTERVAL", "60"))


def _sync_problems(db: Session) -> None:
    """Upsert problems from problems.json into the database."""
    global _problems_file_mtime
    try:
        current_mtime = os.path.getmtime(_PROBLEMS_FILE)
    except OSError:
        logger.warning("problems.json not found at %s", _PROBLEMS_FILE)
        return

    if current_mtime == _problems_file_mtime:
        return  # file unchanged

    with open(_PROBLEMS_FILE) as f:
        problems = json.load(f)

    for p in problems:
        existing = db.query(DBProblem).filter(DBProblem.id == p["id"]).first()
        if existing:
            existing.title = p["title"]
            existing.description = p["description"]
            existing.difficulty = p["difficulty"]
            existing.starter_code = p["starter_code"]
            existing.test_cases = p["test_cases"]
        else:
            db.add(DBProblem(**p))
    db.commit()

    _problems_file_mtime = current_mtime
    logger.info("Synced %d problems from problems.json", len(problems))


async def _problem_reload_loop() -> None:
    """Background task: periodically check problems.json for changes."""
    while True:
        await asyncio.sleep(PROBLEM_RELOAD_INTERVAL)
        db = next(get_db())
        try:
            _sync_problems(db)
        except Exception:
            logger.exception("Error reloading problems")
        finally:
            db.close()


def _row_to_problem(row: DBProblem) -> Problem:
    return Problem(
        id=row.id,
        title=row.title,
        description=row.description,
        difficulty=row.difficulty,
        test_cases=[TestCase(**tc) for tc in row.test_cases],
        starter_code=row.starter_code,
    )


# ---------------------------------------------------------------------------
# Rate-limit helpers
# ---------------------------------------------------------------------------

def _count_recent_actions(db: Session, username: str, action: str, window_seconds: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    return db.query(DBRateLimit).filter(
        DBRateLimit.username == username,
        DBRateLimit.action == action,
        DBRateLimit.timestamp > cutoff,
    ).count()


def _record_action(db: Session, username: str, action: str) -> None:
    db.add(DBRateLimit(
        username=username,
        action=action,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))
    db.commit()


def _get_last_action_time(db: Session, username: str, action: str) -> datetime | None:
    row = db.query(DBRateLimit).filter(
        DBRateLimit.username == username,
        DBRateLimit.action == action,
    ).order_by(DBRateLimit.timestamp.desc()).first()
    if row:
        return datetime.fromisoformat(row.timestamp).replace(tzinfo=timezone.utc)
    return None


def _check_submission_rate(db: Session, username: str) -> None:
    recent_count = _count_recent_actions(db, username, "submit", SUBMIT_RATE_WINDOW_SECONDS)
    if recent_count == 0:
        return

    cooldown = min(
        SUBMIT_RATE_BASE_SECONDS * (2 ** (recent_count - 1)),
        SUBMIT_RATE_MAX_COOLDOWN,
    )

    last_submit = _get_last_action_time(db, username, "submit")
    if last_submit:
        elapsed = (datetime.now(timezone.utc) - last_submit).total_seconds()
        if elapsed < cooldown:
            retry_after = math.ceil(cooldown - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limited. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )


def _cleanup_expired_records(db: Session) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.query(DBChallenge).filter(DBChallenge.expires_at < now).delete()
    db.query(DBSession).filter(DBSession.expires_at < now).delete()
    # Clean up old rate-limit entries (older than the longest window)
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(
        SUBMIT_RATE_WINDOW_SECONDS, CHALLENGE_RATE_WINDOW, VERIFY_FAIL_WINDOW
    ))).isoformat()
    db.query(DBRateLimit).filter(DBRateLimit.timestamp < cutoff).delete()
    db.commit()


def _sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename)
    # Remove null bytes and control characters
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)
    if not name:
        name = "solution.unknown"
    return name


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def require_auth(
    authorization: str = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    session = db.query(DBSession).filter(DBSession.token == token).first()
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if datetime.fromisoformat(session.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session.username


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "project": "cmdcode",
        "status": "online",
        "message": "The judge is ready."
    }


# ---------------------------------------------------------------------------
# Public API endpoints (no token required)
# ---------------------------------------------------------------------------

@app.get("/users/{username}/stats")
def user_stats(
    username: str,
    current_user: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return submission statistics for the authenticated user."""
    if username != current_user:
        raise HTTPException(status_code=403, detail="Cannot view another user's stats")

    submissions = db.query(DBSubmission).filter(DBSubmission.username == username).all()
    total = len(submissions)
    accepted = sum(1 for s in submissions if s.passed)
    unique_solved = db.query(func.count(func.distinct(DBSubmission.problem_id))).filter(
        DBSubmission.username == username,
        DBSubmission.passed == True,
    ).scalar() or 0

    accuracy = round(accepted / total * 100, 1) if total > 0 else 0.0

    from collections import Counter
    lang_counts = Counter(s.language for s in submissions)
    favorite_language = lang_counts.most_common(1)[0][0] if lang_counts else None

    leaderboard = (
        db.query(
            DBSubmission.username,
            func.count(func.distinct(DBSubmission.problem_id)).label("solved"),
        )
        .filter(DBSubmission.passed == True)
        .group_by(DBSubmission.username)
        .order_by(func.count(func.distinct(DBSubmission.problem_id)).desc())
        .all()
    )
    rank = next((i + 1 for i, r in enumerate(leaderboard) if r.username == username), None)

    return {
        "username": username,
        "total_submissions": total,
        "accepted_submissions": accepted,
        "unique_problems_solved": unique_solved,
        "accuracy_rate": accuracy,
        "favorite_language": favorite_language,
        "rank": rank,
    }


@app.get("/users/{username}/history")
def user_history(
    username: str,
    limit: int = 20,
    current_user: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return recent submission history for the authenticated user."""
    if username != current_user:
        raise HTTPException(status_code=403, detail="Cannot view another user's history")

    limit = min(max(limit, 1), 100)

    rows = (
        db.query(DBSubmission)
        .filter(DBSubmission.username == username)
        .order_by(DBSubmission.id.desc())
        .limit(limit)
        .all()
    )

    problem_cache: dict[int, DBProblem] = {}
    result = []
    for s in rows:
        if s.problem_id not in problem_cache:
            problem_cache[s.problem_id] = db.query(DBProblem).filter(DBProblem.id == s.problem_id).first()
        problem = problem_cache[s.problem_id]
        result.append({
            "submission_id": s.id,
            "problem_id": s.problem_id,
            "problem_title": problem.title if problem else f"Problem #{s.problem_id}",
            "language": s.language,
            "verdict": "Accepted" if s.passed else "Wrong Answer",
            "submitted_at": s.submitted_at,
            "size_bytes": s.size_bytes,
        })
    return result


@app.get("/api/leaderboard")
def api_leaderboard(db: Session = Depends(get_db)):
    """Return users ranked by number of unique problems solved (accepted)."""
    rows = (
        db.query(
            DBSubmission.username,
            func.count(func.distinct(DBSubmission.problem_id)).label("solved"),
        )
        .filter(DBSubmission.passed == True)
        .group_by(DBSubmission.username)
        .order_by(func.count(func.distinct(DBSubmission.problem_id)).desc())
        .all()
    )
    return [{"rank": i + 1, "username": r.username, "solved": r.solved} for i, r in enumerate(rows)]


@app.get("/api/problems/public")
def api_problems_public(db: Session = Depends(get_db)):
    """Return problem metadata (no test cases or starter code) without auth."""
    rows = db.query(DBProblem).all()
    return [
        {"id": p.id, "title": p.title, "difficulty": p.difficulty, "description": p.description}
        for p in rows
    ]


# ---------------------------------------------------------------------------
# Auth endpoints  (no token required)
# ---------------------------------------------------------------------------

@app.post("/auth/register", status_code=201)
def auth_register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # IP-based registration rate limiting
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=REGISTER_IP_WINDOW)
    _register_ip_counts[client_ip] = [
        t for t in _register_ip_counts[client_ip] if t > cutoff
    ]
    if len(_register_ip_counts[client_ip]) >= REGISTER_IP_LIMIT:
        raise HTTPException(status_code=429, detail="Too many registrations. Try again later.")
    _register_ip_counts[client_ip].append(now)

    if not req.username.isalnum() or not (3 <= len(req.username) <= 20):
        raise HTTPException(status_code=422, detail="Username must be 3-20 alphanumeric characters")
    if db.query(DBUser).filter(DBUser.username == req.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    try:
        pub_key = serialization.load_pem_public_key(req.public_key.encode())
        if not isinstance(pub_key, Ed25519PublicKey):
            raise ValueError("Not Ed25519")
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid Ed25519 public key")

    db.add(DBUser(
        username=req.username,
        email=req.email,
        public_key_pem=req.public_key,
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    db.commit()

    # Opportunistic cleanup of expired records
    _cleanup_expired_records(db)

    return {"message": "registered", "username": req.username}


@app.get("/auth/challenge/{username}")
def auth_challenge(username: str, db: Session = Depends(get_db)):
    if not db.query(DBUser).filter(DBUser.username == username).first():
        raise HTTPException(status_code=404, detail="User not found")

    # Rate limit challenge requests per username
    recent_challenges = _count_recent_actions(db, username, "challenge", CHALLENGE_RATE_WINDOW)
    if recent_challenges >= CHALLENGE_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many challenge requests. Try again later.")

    challenge_id = str(uuid.uuid4())
    nonce = secrets.token_bytes(32).hex()
    db.add(DBChallenge(
        challenge_id=challenge_id,
        username=username,
        nonce=nonce,
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    ))
    _record_action(db, username, "challenge")

    # Opportunistic cleanup
    _cleanup_expired_records(db)

    return {"challenge_id": challenge_id, "nonce": nonce}


@app.post("/auth/verify")
def auth_verify(req: VerifyRequest, db: Session = Depends(get_db)):
    # Rate limit failed verification attempts
    recent_failures = _count_recent_actions(db, req.username, "verify_fail", VERIFY_FAIL_WINDOW)
    if recent_failures >= VERIFY_FAIL_LIMIT:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Account temporarily locked.")

    challenge = db.query(DBChallenge).filter(DBChallenge.challenge_id == req.challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=401, detail="Challenge expired or not found")
    if datetime.fromisoformat(challenge.expires_at) < datetime.now(timezone.utc):
        db.delete(challenge)
        db.commit()
        raise HTTPException(status_code=401, detail="Challenge expired or not found")
    if challenge.username != req.username:
        raise HTTPException(status_code=401, detail="Username mismatch")

    user = db.query(DBUser).filter(DBUser.username == req.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        pub_key = serialization.load_pem_public_key(user.public_key_pem.encode())
        signature = base64.b64decode(req.signature)
        nonce_bytes = bytes.fromhex(challenge.nonce)
        pub_key.verify(signature, nonce_bytes)
    except InvalidSignature:
        _record_action(db, req.username, "verify_fail")
        raise HTTPException(status_code=401, detail="Invalid signature")
    except Exception:
        _record_action(db, req.username, "verify_fail")
        raise HTTPException(status_code=401, detail="Verification failed")

    # Consume challenge to prevent replay
    db.delete(challenge)

    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    db.add(DBSession(
        token=token,
        username=req.username,
        expires_at=expires_at.isoformat(),
    ))
    db.commit()
    return {"token": token, "expires_at": expires_at.isoformat()}


# ---------------------------------------------------------------------------
# Recovery endpoints
# ---------------------------------------------------------------------------

def _make_recovery_code() -> str:
    """Generate a human-readable recovery code in XXXXXX-XXXXXX-XXXXXX format."""
    raw = secrets.token_hex(9).upper()  # 18 uppercase hex chars (72 bits of entropy)
    return f"{raw[:6]}-{raw[6:12]}-{raw[12:]}"


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@app.post("/auth/recovery-codes", status_code=201)
def auth_generate_recovery_codes(
    username: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Generate a fresh set of recovery codes. All previous unused codes are invalidated."""
    # Invalidate all existing codes for this user
    db.query(DBRecoveryCode).filter(DBRecoveryCode.username == username).delete()

    plaintext_codes = []
    now = datetime.now(timezone.utc).isoformat()
    for _ in range(RECOVERY_CODE_COUNT):
        code = _make_recovery_code()
        plaintext_codes.append(code)
        db.add(DBRecoveryCode(
            id=str(uuid.uuid4()),
            username=username,
            code_hash=_hash_recovery_code(code),
            used=False,
            created_at=now,
        ))
    db.commit()

    return {
        "codes": plaintext_codes,
        "warning": (
            "SAVE THESE CODES NOW — they will not be shown again. "
            "Store them somewhere safe and outside ~/.cmdcode/ "
            "(e.g. a password manager, printed paper, or encrypted USB drive)."
        ),
    }


@app.post("/auth/recover")
def auth_recover(req: RecoverRequest, db: Session = Depends(get_db)):
    """Replace a user's public key using a valid one-time recovery code."""
    # Rate-limit recovery attempts per username to prevent brute force
    recent_attempts = _count_recent_actions(db, req.username, "recover_attempt", RECOVER_RATE_WINDOW)
    if recent_attempts >= RECOVER_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many recovery attempts. Try again in an hour.",
        )
    _record_action(db, req.username, "recover_attempt")

    user = db.query(DBUser).filter(DBUser.username == req.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate the new public key before touching anything
    try:
        pub_key = serialization.load_pem_public_key(req.new_public_key.encode())
        if not isinstance(pub_key, Ed25519PublicKey):
            raise ValueError("Not Ed25519")
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid Ed25519 public key")

    # Normalise the submitted code and look it up
    submitted_hash = _hash_recovery_code(req.recovery_code.strip().upper())
    recovery_code = db.query(DBRecoveryCode).filter(
        DBRecoveryCode.username == req.username,
        DBRecoveryCode.code_hash == submitted_hash,
        DBRecoveryCode.used == False,
    ).first()

    if not recovery_code:
        raise HTTPException(status_code=401, detail="Invalid or already-used recovery code")

    # Mark code as consumed
    recovery_code.used = True

    # Rotate the public key
    user.public_key_pem = req.new_public_key

    # Invalidate all active sessions so the old key can't be used via cached tokens
    db.query(DBSession).filter(DBSession.username == req.username).delete()

    db.commit()

    return {
        "message": "Key updated successfully",
        "username": user.username,
        "email": user.email,
    }


# ---------------------------------------------------------------------------
# Protected problem endpoints
# ---------------------------------------------------------------------------

@app.get("/problems")
def list_problems(username: str = Depends(require_auth), db: Session = Depends(get_db)):
    return [_row_to_problem(p) for p in db.query(DBProblem).all()]


@app.get("/problems/{problem_id}")
def get_problem(problem_id: int, username: str = Depends(require_auth), db: Session = Depends(get_db)):
    row = db.query(DBProblem).filter(DBProblem.id == problem_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Problem not found")
    return _row_to_problem(row)


@app.post("/submit/{problem_id}")
async def submit_solution(
    problem_id: int,
    file: UploadFile = File(...),
    username: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    # Exponential backoff rate limiting
    _check_submission_rate(db, username)

    filename = _sanitize_filename(file.filename or "solution.unknown")
    content_type = file.content_type or ""
    file_ext = os.path.splitext(filename)[1].lower()

    raw_bytes = await file.read()

    # File size limit
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 1 MB.")

    try:
        if "base64" in content_type.lower():
            base64_str = raw_bytes.decode("utf-8").strip()
            code_bytes = base64.b64decode(base64_str, validate=True)
            code = code_bytes.decode("utf-8")
        else:
            code = raw_bytes.decode("utf-8")

        code = code.replace("\r\n", "\n").replace("\r", "\n")
        code = "\n".join(line.rstrip() for line in code.splitlines()) + "\n"
        code = code.expandtabs(4)

    except base64.binascii.Error:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File contains invalid UTF-8 after base64 decode")

    problem_row = db.query(DBProblem).filter(DBProblem.id == problem_id).first()
    if not problem_row:
        raise HTTPException(status_code=404, detail="Problem not found")

    language_id = LANGUAGE_IDS.get(file_ext)
    if not language_id:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {file_ext}")

    results = []
    all_passed = True

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, test in enumerate(problem_row.test_cases):
            payload = {
                "source_code": code,
                "language_id": language_id,
                "stdin": test["input"],
                "expected_output": test["output"].strip(),
            }

            try:
                resp = await client.post(f"{JUDGE0_URL}/submissions?wait=true", json=payload)
                resp.raise_for_status()
                result = resp.json()

                status_id = result.get("status", {}).get("id", 0)
                stdout = (result.get("stdout") or "").strip()
                expected = test["output"].strip()

                passed = (status_id == 3) and (stdout == expected)
                if not passed:
                    all_passed = False

                results.append({
                    "test_case": i + 1,
                    "hidden": test["hidden"],
                    "passed": passed,
                    "status": result.get("status", {}).get("description", "Unknown"),
                    "time": result.get("time", "0"),
                    "memory": result.get("memory", 0),
                    "stdout": stdout[:200],
                    "expected": expected[:200] if not test["hidden"] else None,
                })

            except httpx.HTTPError as e:
                results.append({
                    "test_case": i + 1,
                    "passed": False,
                    "error": f"Judge0 error: {str(e)}",
                })
                all_passed = False

    submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # Record submission for rate limiting
    _record_action(db, username, "submit")

    db.add(DBSubmission(
        problem_id=problem_id,
        username=username,
        filename=filename,
        code=code,
        language=file_ext,
        submitted_at=submitted_at,
        size_bytes=len(code),
        status="Accepted" if all_passed else "Wrong",
        passed=all_passed,
        results=results,
    ))
    db.commit()

    return SubmissionResponse(
        problem_id=problem_id,
        filename=filename,
        code=code,
        language=file_ext,
        submitted_at=submitted_at,
        size_bytes=len(code),
        status="Accepted" if all_passed else "Wrong",
        passed=all_passed,
        results=results,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)
