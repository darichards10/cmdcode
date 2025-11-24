# server/main.py
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI(title="cmdcode Server", description="Your personal coding judge")
APP_PORT = int(os.getenv("APP_PORT", 8000))

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
    submission_id: int
    problem_id: int
    filename: str
    code: str
    language: str = "cpp"
    submitted_at: str
    size_bytes: int
    status: str = "received"
    passed: bool = False
    
# Will be in DB l8r
submission_counter = 1 
submissions_log: List[Submission] = []

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
        "total_submissions": len(submissions_log),
        "message": "Your personal judge is ready."
    }
    
@app.get("/problems/{problem_id}")
def get_problem(problem_id: int):
    if problem_id not in PROBLEMS_DB:
        raise HTTPException(status_code=404, detail="Problem not found")
    return PROBLEMS_DB[problem_id]

@app.post("/submit/{problem_id}")
async def submit_solution(problem_id: int, file: UploadFile = File(...)):
    global submission_counter

    content = await file.read()
    code = content.decode("utf-8")

    submission = Submission(
        submission_id=submission_counter,
        problem_id=problem_id,
        filename=file.filename,
        code=code,
        submitted_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        size_bytes=len(content),
        passed=True
    )

    submissions_log.append(submission)
    submission_counter += 1
    return submission

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)