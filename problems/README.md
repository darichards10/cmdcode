# Contributing Problems

Each problem lives in its own folder under `problems/`. To add a new problem, create a folder and open a pull request.

## Folder Structure

```
problems/NNN-problem-slug/
├── problem.json          # Metadata, description, starter code
├── tests/
│   ├── 01.in             # stdin for test 1
│   ├── 01.out            # expected stdout for test 1
│   ├── 02.in / 02.out    # more tests...
│   └── ...
└── solutions/
    └── solution.py       # Reference solution (required)
```

## Adding a Problem

1. Pick the next available ID number (check existing folders).

2. Create the folder:
   ```
   mkdir -p problems/009-my-problem/{tests,solutions}
   ```

3. Write `problem.json`:
   ```json
   {
     "id": 9,
     "title": "My Problem",
     "description": "Read N from stdin and ...",
     "difficulty": "Easy",
     "hidden_tests_start": 3,
     "starter_code": {
       "python": "# Your code here",
       "cpp": "#include <iostream>\nint main() {\n    // Your code here\n    return 0;\n}",
       "java": "public class Solution {\n    public static void main(String[] args) {\n        // Your code here\n    }\n}"
     }
   }
   ```

   - `hidden_tests_start`: test number from which tests are hidden from users (e.g., `3` means tests 01 and 02 are visible, 03+ are hidden)

4. Add test cases as `tests/NN.in` and `tests/NN.out` files. Include at least:
   - 2 visible tests (simple examples from the description)
   - 2 hidden tests (edge cases)

5. Write a reference solution in `solutions/solution.py`.

6. Validate locally:
   ```
   python problems/build.py --problem 009-my-problem
   ```

7. Generate the server seed file:
   ```
   python problems/build.py --generate
   ```

8. Open a pull request. CI will validate your solution automatically.

## Build Script

```
python problems/build.py                           # validate + generate
python problems/build.py --validate                 # only run solutions against tests
python problems/build.py --generate                 # only regenerate server/problems.json
python problems/build.py --problem 003-fizzbuzz     # validate a single problem
```

## Guidelines

- Descriptions should include at least one example with input/output
- Test inputs must end with a newline
- Expected outputs must end with a newline
- Difficulty levels: Easy, Medium, Hard
- Starter code should compile/run without errors (even if it doesn't solve the problem)
