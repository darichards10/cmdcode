# server/main.py
import base64
import secrets
import uuid
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import List, Dict
import uvicorn
import os
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

load_dotenv()
app = FastAPI(title="cmdcode Server", description="Your personal coding judge")
APP_PORT = int(os.getenv("APP_PORT", 8000))
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0:2358")

# In-memory auth stores
USERS_DB: dict = {}       # username -> {username, email, public_key_pem, created_at}
CHALLENGES_DB: dict = {}  # challenge_id -> {username, nonce, expires_at}
SESSIONS_DB: dict = {}    # token -> {username, expires_at}

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

class Submission(BaseModel):
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
    
LANGUAGE_IDS = {
    ".cpp": 54,    # C++ (g++)
    ".c": 52,      # C
    ".py": 71,     # Python 3
    ".java": 62,   # Java
    ".js": 63,     # Node.js
    ".ts": 74,     # TypeScript
    ".go": 60,     # Go
    ".rs": 73,     # Rust
}

# In-memory DB 4 now 
PROBLEMS_DB = {
    1: Problem(
        id=1,
        title="Hello World",
        description="Write a program that prints 'Hello, World!' exactly.",
        difficulty="Easy",
        test_cases=[
            TestCase(input="", output="Hello, World!\n", hidden=False),
            TestCase(input="", output="Hello, World!\n", hidden=True),
        ],
        starter_code={
            "cpp": '#include <iostream>\nint main() {\n    // Your code here\n    return 0;\n}',
            "python": 'print("Hello, World!")',
            "java": 'public class Solution {\n    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }\n}'
        }
    )
}

def require_auth(authorization: str = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    session = SESSIONS_DB.get(token)
    if not session or datetime.now(timezone.utc) > session["expires_at"]:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session["username"]


@app.get("/")
def root():
    return {
        "project": "cmdcode",
        "status": "online",
        "message": "The judge is ready."
    }


@app.post("/auth/register", status_code=201)
def auth_register(req: RegisterRequest):
    if not req.username.isalnum() or not (3 <= len(req.username) <= 20):
        raise HTTPException(status_code=422, detail="Username must be 3-20 alphanumeric characters")
    if req.username in USERS_DB:
        raise HTTPException(status_code=409, detail="Username already taken")
    try:
        pub_key = serialization.load_pem_public_key(req.public_key.encode())
        if not isinstance(pub_key, Ed25519PublicKey):
            raise ValueError("Not Ed25519")
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid Ed25519 public key")

    USERS_DB[req.username] = {
        "username": req.username,
        "email": req.email,
        "public_key_pem": req.public_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"message": "registered", "username": req.username}


@app.get("/auth/challenge/{username}")
def auth_challenge(username: str):
    if username not in USERS_DB:
        raise HTTPException(status_code=404, detail="User not found")
    challenge_id = str(uuid.uuid4())
    nonce = secrets.token_bytes(32).hex()
    CHALLENGES_DB[challenge_id] = {
        "username": username,
        "nonce": nonce,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
    }
    return {"challenge_id": challenge_id, "nonce": nonce}


@app.post("/auth/verify")
def auth_verify(req: VerifyRequest):
    challenge = CHALLENGES_DB.get(req.challenge_id)
    if not challenge or datetime.now(timezone.utc) > challenge["expires_at"]:
        raise HTTPException(status_code=401, detail="Challenge expired or not found")
    if challenge["username"] != req.username:
        raise HTTPException(status_code=401, detail="Username mismatch")

    user = USERS_DB.get(req.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        pub_key = serialization.load_pem_public_key(user["public_key_pem"].encode())
        signature = base64.b64decode(req.signature)
        nonce_bytes = bytes.fromhex(challenge["nonce"])
        pub_key.verify(signature, nonce_bytes)
    except InvalidSignature:
        raise HTTPException(status_code=401, detail="Invalid signature")
    except Exception:
        raise HTTPException(status_code=401, detail="Verification failed")

    del CHALLENGES_DB[req.challenge_id]

    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    SESSIONS_DB[token] = {"username": req.username, "expires_at": expires_at}
    return {"token": token, "expires_at": expires_at.isoformat()}


@app.get("/problems")
def list_problems(username: str = Depends(require_auth)):
    return list(PROBLEMS_DB.values())


@app.get("/problems/{problem_id}")
def get_problem(problem_id: int, username: str = Depends(require_auth)):
    if problem_id not in PROBLEMS_DB:
        raise HTTPException(status_code=404, detail="Problem not found")
    return PROBLEMS_DB[problem_id]

@app.post("/submit/{problem_id}")
async def submit_solution(
    problem_id: int,
    file: UploadFile = File(...),
    username: str = Depends(require_auth),
):
    filename = file.filename or "solution.unknown"
    content_type = file.content_type or ""
    file_ext = os.path.splitext(filename)[1].lower()
    
    raw_bytes = await file.read()  
    try:
        if "base64" in content_type.lower():
            base64_str = raw_bytes.decode("utf-8").strip()
            print(f"Base64 received: {base64_str[:100]}...")
            
            code_bytes = base64.b64decode(base64_str, validate=True)
            code = code_bytes.decode("utf-8")
        else:
            code = raw_bytes.decode("utf-8")

        code = code.replace("\r\n", "\n").replace("\r", "\n")
        code = "\n".join(line.rstrip() for line in code.splitlines()) + "\n"
        code = code.expandtabs(4)

        print(f"Decoded clean code ({len(code)} chars):\n{code}")

    except base64.binascii.Error:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File contains invalid UTF-8 after base64 decode")
    
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    code = "\n".join(line.rstrip() for line in code.splitlines()) + "\n"
    code = code.expandtabs(4)

    # Get problem from in-memory DB
    if problem_id not in PROBLEMS_DB:
        raise HTTPException(status_code=404, detail="Problem not found")
    problem = PROBLEMS_DB[problem_id]

    # Determine language
    language_id = LANGUAGE_IDS.get(file_ext)
    if not language_id:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {file_ext}")

    # Run all test cases
    results = []
    all_passed = True

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, test in enumerate(problem.test_cases):
            payload = {
                "source_code": code,
                "language_id": language_id,
                "stdin": test.input,
                "expected_output": test.output.strip(),
            }

            try:
                
                resp = await client.post(f"{JUDGE0_URL}/submissions?wait=true", json=payload)
                resp.raise_for_status()
                result = resp.json()

                # Judge0 status codes: 3=Accepted, 4=Wrong Answer, 5=TLE, 6=MLE, etc.
                status_id = result.get("status", {}).get("id", 0)
                stdout = (result.get("stdout") or "").strip()

                expected = test.output.strip()

                passed = (status_id == 3) and (stdout == expected)
                if not passed:
                    all_passed = False

                results.append({
                    "test_case": i + 1,
                    "hidden": test.hidden,
                    "passed": passed,
                    "status": result.get("status", {}).get("description", "Unknown"),
                    "time": result.get("time", "0"),
                    "memory": result.get("memory", 0),
                    "stdout": stdout[:200],  # truncate for response
                    "expected": expected[:200] if not test.hidden else None
                })

            except httpx.HTTPError as e:
                results.append({
                    "test_case": i + 1,
                    "passed": False,
                    "error": f"Judge0 error: {str(e)}"
                })
                all_passed = False

    # Create final submission record
    submission = Submission(
        problem_id=problem_id,
        filename=filename,
        code=code,
        language=file_ext,
        submitted_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        size_bytes=len(code),
        status="Accepted" if all_passed else "Wrong",
        passed=all_passed,
        results=results  # optional: add to model if you want
    )

    return submission

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)