# Plan: Adding Problems to the Database

## Current State

- **1 seeded problem** ("Hello World") hardcoded in `SEED_PROBLEMS` list in `server/main.py`
- `_seed_problems()` runs on startup and only inserts if the `problems` table is empty
- No admin API or CLI command to add/manage problems
- Schema already supports everything needed: `DBProblem` has `id`, `title`, `description`, `difficulty`, `starter_code` (JSON), `test_cases` (JSON)

## Goal

Enable adding problems to the database so users can fetch and submit solutions to them. Two approaches below — we should pick one (or both).

---

## Approach 1: Expand the Seed Data File (Simplest)

Move problems out of `main.py` into a dedicated `server/problems.json` file, then load it during seeding.

### Steps

1. **Create `server/problems.json`** — a JSON array of problem objects, each with:
   ```json
   {
     "id": 2,
     "title": "Sum Two Numbers",
     "description": "Read two integers from stdin and print their sum.",
     "difficulty": "Easy",
     "test_cases": [
       {"input": "3 5\n", "output": "8\n", "hidden": false},
       {"input": "0 0\n", "output": "0\n", "hidden": true}
     ],
     "starter_code": {
       "cpp": "#include <iostream>\nint main() {\n    // Your code here\n    return 0;\n}",
       "python": "# Read two integers and print their sum",
       "java": "import java.util.Scanner;\npublic class Solution {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n    }\n}"
     }
   }
   ```

2. **Update `_seed_problems()` in `server/main.py`**:
   - Load problems from `problems.json` instead of the hardcoded `SEED_PROBLEMS` list
   - Use **upsert logic**: for each problem in the file, insert if the ID doesn't exist yet (so new problems get added on restart without wiping existing submissions)

3. **Add 5-10 starter problems** spanning Easy/Medium/Hard:
   - Hello World (existing)
   - Sum Two Numbers (Easy)
   - FizzBuzz (Easy)
   - Reverse a String (Easy)
   - Palindrome Check (Medium)
   - Two Sum (Medium)
   - Fibonacci (Medium)
   - Longest Common Subsequence (Hard)
   - Matrix Multiplication (Hard)

4. **Update tests** to verify multi-problem seeding and upsert behavior

### Pros
- Simplest to implement
- Problems are version-controlled
- No new endpoints or auth needed

### Cons
- Requires server restart to add new problems
- No runtime management

---

## Approach 2: Admin API Endpoints (More Flexible)

Add protected API endpoints for creating/updating/deleting problems at runtime.

### Steps

1. **Add admin role to `DBUser` model** (`server/models.py`):
   - Add `is_admin` column (Boolean, default False)

2. **Create admin auth dependency** (`server/main.py`):
   - `require_admin()` — wraps `require_auth()` and checks `is_admin == True`

3. **Add admin API endpoints**:
   - `POST /admin/problems` — Create a new problem
     - Body: `{title, description, difficulty, test_cases, starter_code}`
     - Validates all fields, auto-assigns next ID
     - Returns: created problem with ID
   - `PUT /admin/problems/{id}` — Update an existing problem
     - Partial update supported
   - `DELETE /admin/problems/{id}` — Delete a problem
     - Reject if submissions exist (or cascade with confirmation)
   - `GET /admin/problems/{id}/test` — Dry-run: submit a solution against the problem without recording it

4. **Add CLI admin commands** (`cli/src/cmdcode/cli.py`):
   - `cmdcode admin add-problem --file problem.json` — POST a problem definition from a JSON file
   - `cmdcode admin list-problems` — List all problems (admin view with hidden test cases)
   - `cmdcode admin delete-problem <ID>` — Delete a problem

5. **Seed the first admin user**:
   - Environment variable `ADMIN_USERS=username1,username2` checked during auth
   - Or a CLI command: `cmdcode admin promote <username>` (requires server-side secret key)

6. **Update tests** for all new endpoints and admin auth

### Pros
- Runtime problem management without restarts
- Role-based access control
- Scalable for multiple problem authors

### Cons
- More code, more attack surface
- Needs admin auth infrastructure

---

## Recommended Approach: Start with Approach 1, then layer Approach 2

### Phase 1 (Immediate) — Seed file with problems
1. Create `server/problems.json` with 8-10 problems
2. Update `_seed_problems()` to load from file with upsert logic
3. Remove hardcoded `SEED_PROBLEMS` from `main.py`
4. Update tests
5. **Files changed**: `server/main.py`, `server/problems.json`, `tests/server/test_api.py`

### Phase 2 (Follow-up) — Admin API
1. Add `is_admin` to `DBUser`
2. Add admin endpoints (POST/PUT/DELETE)
3. Add CLI admin commands
4. Add admin tests
5. **Files changed**: `server/models.py`, `server/main.py`, `cli/src/cmdcode/cli.py`, `tests/server/test_api.py`, `tests/cli/test_cli.py`

---

## Problem Format Spec

Each problem in `problems.json`:

| Field          | Type                          | Required | Description                           |
|----------------|-------------------------------|----------|---------------------------------------|
| `id`           | int                           | yes      | Unique problem ID                     |
| `title`        | string                        | yes      | Problem title                         |
| `description`  | string                        | yes      | Full problem statement (markdown ok)  |
| `difficulty`   | "Easy" \| "Medium" \| "Hard" | yes      | Difficulty tier                       |
| `test_cases`   | array of TestCase             | yes      | At least 1 visible + 1 hidden        |
| `starter_code` | object {lang: code}           | yes      | At least `cpp` and `python`           |

Each `TestCase`:

| Field    | Type    | Required | Description                    |
|----------|---------|----------|--------------------------------|
| `input`  | string  | yes      | stdin input                    |
| `output` | string  | yes      | expected stdout (exact match)  |
| `hidden` | boolean | no       | hidden from user (default false)|
