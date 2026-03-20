# Plan: Adding Problems to the Database

## Current State (Phase 1 Complete)

- **8 seeded problems** in `server/problems.json` (Hello World, Sum Two Numbers, FizzBuzz, etc.)
- `_seed_problems()` loads from JSON with upsert logic (insert if ID missing, skip if exists)
- Each problem has visible + hidden test cases and starter code for C++, Python, Java

---

## Phase 2: Contributor-Friendly `problems/` Directory

Move from a flat JSON file to a structured `problems/` directory where each problem is self-contained with metadata, test cases, and **reference solutions**. A build script validates solutions and generates the server seed file. Contributors add a folder and open a PR.

### Directory Structure

```
problems/
├── build.py                     # Validates solutions & generates server/problems.json
├── README.md                    # How to contribute a problem
├── 001-hello-world/
│   ├── problem.json             # Metadata: title, description, difficulty, starter_code
│   ├── tests/
│   │   ├── 01.in                # stdin input
│   │   ├── 01.out               # expected stdout
│   │   ├── 02.in
│   │   ├── 02.out
│   │   ├── 03.in                # hidden test (convention: 03+ are hidden)
│   │   └── 03.out
│   └── solutions/
│       ├── solution.py          # Reference solution (Python)
│       ├── solution.cpp         # Reference solution (C++)
│       └── solution.java        # Reference solution (Java)
├── 002-sum-two-numbers/
│   ├── problem.json
│   ├── tests/
│   └── solutions/
└── ...
```

### `problem.json` Format

```json
{
  "id": 1,
  "title": "Hello World",
  "description": "Write a program that prints 'Hello, World!' exactly.",
  "difficulty": "Easy",
  "hidden_tests_start": 3,
  "starter_code": {
    "cpp": "#include <iostream>\nint main() {\n    // Your code here\n    return 0;\n}",
    "python": "# Your code here",
    "java": "public class Solution {\n    public static void main(String[] args) {\n        // Your code here\n    }\n}"
  }
}
```

Test cases are **files** (`tests/01.in`, `tests/01.out`, etc.) instead of inline JSON. The `hidden_tests_start` field marks which numbered tests are hidden from users (e.g., tests 3+ are hidden).

### `build.py` — Build & Validate Script

The build script does two things:

1. **Validate** — Run each reference solution against the test cases locally
2. **Generate** — Produce `server/problems.json` from the problem folders

```
python problems/build.py [--validate] [--generate] [--problem 001-hello-world]
```

| Flag | Behavior |
|------|----------|
| `--validate` | Run reference solutions against test cases, fail on mismatch |
| `--generate` | Assemble `server/problems.json` from all problem folders |
| (no flags) | Both validate and generate |
| `--problem X` | Only process a specific problem folder |

Validation runs solutions as **subprocesses** with:
- Timeout (e.g. 10s per test case)
- stdin piped from `*.in` files
- stdout compared to `*.out` files
- Non-zero exit or mismatch → build fails

### Steps

1. **Create `problems/` directory structure**
   - Convert existing 8 problems from `server/problems.json` into individual folders
   - Write reference solutions for each (at minimum Python)

2. **Write `problems/build.py`**
   - Discover problem folders (`problems/NNN-*/`)
   - Parse `problem.json` + collect test files
   - Validate: run each `solutions/solution.*` against test inputs, compare outputs
   - Generate: assemble all problems into `server/problems.json`

3. **Update CI pipeline** (`.github/workflows/test.yml`)
   - Add a step that runs `python problems/build.py --validate` before tests
   - This ensures reference solutions stay correct as problems are added/modified
   - Optionally run `--generate` and fail if `server/problems.json` is out of date

4. **Write `problems/README.md`** (contributing guide)
   - How to add a new problem: create folder, write problem.json, add tests, add solutions
   - Run `python problems/build.py --problem NNN-my-problem` locally to validate
   - Open a PR

5. **Update tests**
   - Test `build.py` itself: valid problem passes, broken solution fails
   - Ensure generated `problems.json` matches expected schema

### Files Changed/Created

| File | Action |
|------|--------|
| `problems/build.py` | New — build & validation script |
| `problems/README.md` | New — contributor guide |
| `problems/001-hello-world/` | New — problem folder (×8 for all existing problems) |
| `.github/workflows/test.yml` | Modified — add validation step |
| `server/problems.json` | Now generated (still committed for deployment simplicity) |

### CI Pipeline Flow

```
PR opened → checkout → install deps → validate problems → run tests → ✓
                                          ↓
                              python problems/build.py --validate
                              (runs all reference solutions against test cases)
```

### Contributor Workflow

```
1. Fork repo
2. mkdir problems/009-my-problem
3. Write problem.json, tests/*.in/*.out, solutions/solution.py
4. Run: python problems/build.py --problem 009-my-problem
5. Run: python problems/build.py --generate  (updates server/problems.json)
6. Open PR — CI validates solutions automatically
```

### Pros
- Problems are self-documenting and easy to review in PRs
- Reference solutions are validated in CI — no broken test cases
- Contributors don't need to understand the server code
- Test case files are easy to diff and review
- `server/problems.json` is generated, not hand-edited

### Cons
- Requires language runtimes in CI (Python at minimum, optionally g++/javac)
- Initial migration effort to split existing problems into folders

---

## Phase 3 (Future): Admin API

Layer runtime problem management on top for trusted users. See original plan for details — `is_admin` on `DBUser`, `POST/PUT/DELETE /admin/problems` endpoints, CLI commands. This is independent of Phase 2 and can be done later.
