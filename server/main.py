# server/main.py
import base64
import secrets
import uuid
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends
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
from models import DBChallenge, DBProblem, DBSession, DBSubmission, DBUser

load_dotenv()


@asynccontextmanager
async def lifespan(application):
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        _seed_problems(db)
    finally:
        db.close()
    yield


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

SEED_PROBLEMS = [
    {
        "id": 1,
        "title": "Hello World",
        "description": "Write a program that prints 'Hello, World!' exactly.",
        "difficulty": "Easy",
        "test_cases": [
            {"input": "", "output": "Hello, World!\n", "hidden": False},
            {"input": "", "output": "Hello, World!\n", "hidden": True},
        ],
        "starter_code": {
            "cpp": '#include <iostream>\nint main() {\n    // Your code here\n    return 0;\n}',
            "python": 'print("Hello, World!")',
            "java": 'public class Solution {\n    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }\n}',
        },
    }
]


def _seed_problems(db: Session) -> None:
    if db.query(DBProblem).count() == 0:
        for p in SEED_PROBLEMS:
            db.add(DBProblem(**p))
        db.commit()


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
def auth_register(req: RegisterRequest, db: Session = Depends(get_db)):
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
    return {"message": "registered", "username": req.username}


@app.get("/auth/challenge/{username}")
def auth_challenge(username: str, db: Session = Depends(get_db)):
    if not db.query(DBUser).filter(DBUser.username == username).first():
        raise HTTPException(status_code=404, detail="User not found")
    challenge_id = str(uuid.uuid4())
    nonce = secrets.token_bytes(32).hex()
    db.add(DBChallenge(
        challenge_id=challenge_id,
        username=username,
        nonce=nonce,
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    ))
    db.commit()
    return {"challenge_id": challenge_id, "nonce": nonce}


@app.post("/auth/verify")
def auth_verify(req: VerifyRequest, db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=401, detail="Invalid signature")
    except Exception:
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
    filename = file.filename or "solution.unknown"
    content_type = file.content_type or ""
    file_ext = os.path.splitext(filename)[1].lower()

    raw_bytes = await file.read()
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

    submitted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
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
