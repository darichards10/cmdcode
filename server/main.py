# server/main.py
import base64
import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI(title="cmdcode Server", description="Your personal coding judge")
APP_PORT = int(os.getenv("APP_PORT", 8000))
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0:2358")

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
    #results: Dict[str, str]
    
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

@app.get("/")
def root():
    return {
        "project": "cmdcode",
        "status": "online",
        "message": "The judge is ready."
    }
    
@app.get("/problems/{problem_id}")
def get_problem(problem_id: int):
    if problem_id not in PROBLEMS_DB:
        raise HTTPException(status_code=404, detail="Problem not found")
    return PROBLEMS_DB[problem_id]

@app.post("/submit/{problem_id}")
async def submit_solution(problem_id: int, file: UploadFile = File(...)):
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