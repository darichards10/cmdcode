#!/usr/bin/env python3
"""Build and validate the problems database.

Usage:
    python problems/build.py                      # validate + generate
    python problems/build.py --validate            # only validate solutions
    python problems/build.py --generate            # only generate server/problems.json
    python problems/build.py --problem 001-hello-world  # single problem
"""
import argparse
import glob
import json
import os
import subprocess
import sys

PROBLEMS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PROBLEMS_DIR)
OUTPUT_FILE = os.path.join(ROOT_DIR, "server", "problems.json")
TIMEOUT_SECONDS = 10

RUNNERS = {
    ".py": lambda path: [sys.executable, path],
}


def discover_problems(single=None):
    """Return sorted list of problem folder paths."""
    if single:
        path = os.path.join(PROBLEMS_DIR, single)
        if not os.path.isdir(path):
            print(f"ERROR: problem folder not found: {single}")
            sys.exit(1)
        return [path]
    pattern = os.path.join(PROBLEMS_DIR, "[0-9][0-9][0-9]-*")
    folders = sorted(glob.glob(pattern))
    if not folders:
        print("ERROR: no problem folders found")
        sys.exit(1)
    return folders


def load_problem(folder):
    """Load problem.json and test cases from a problem folder."""
    meta_path = os.path.join(folder, "problem.json")
    with open(meta_path) as f:
        meta = json.load(f)

    tests_dir = os.path.join(folder, "tests")
    test_files = sorted(glob.glob(os.path.join(tests_dir, "*.in")))
    test_cases = []
    for in_file in test_files:
        out_file = in_file.replace(".in", ".out")
        if not os.path.exists(out_file):
            print(f"  ERROR: missing output file: {out_file}")
            sys.exit(1)
        with open(in_file) as f:
            inp = f.read()
        with open(out_file) as f:
            out = f.read()
        num = int(os.path.basename(in_file).replace(".in", ""))
        hidden = num >= meta.get("hidden_tests_start", 999)
        test_cases.append({"input": inp, "output": out, "hidden": hidden})

    return meta, test_cases


def validate_problem(folder):
    """Run all reference solutions against test cases. Returns True if all pass."""
    name = os.path.basename(folder)
    meta, test_cases = load_problem(folder)
    solutions_dir = os.path.join(folder, "solutions")

    solution_files = []
    for ext in RUNNERS:
        solution_files.extend(glob.glob(os.path.join(solutions_dir, f"*{ext}")))

    if not solution_files:
        print(f"  SKIP {name}: no runnable solutions found")
        return True

    all_passed = True
    for sol_path in sorted(solution_files):
        sol_name = os.path.basename(sol_path)
        ext = os.path.splitext(sol_path)[1]
        cmd = RUNNERS[ext](sol_path)

        for i, tc in enumerate(test_cases, 1):
            try:
                result = subprocess.run(
                    cmd,
                    input=tc["input"],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                print(f"  FAIL {name}/{sol_name} test {i:02d}: timeout ({TIMEOUT_SECONDS}s)")
                all_passed = False
                continue

            if result.returncode != 0:
                print(f"  FAIL {name}/{sol_name} test {i:02d}: non-zero exit ({result.returncode})")
                if result.stderr:
                    print(f"       stderr: {result.stderr.strip()}")
                all_passed = False
                continue

            if result.stdout != tc["output"]:
                print(f"  FAIL {name}/{sol_name} test {i:02d}: output mismatch")
                print(f"       expected: {tc['output']!r}")
                print(f"       got:      {result.stdout!r}")
                all_passed = False
                continue

        if all_passed:
            print(f"  OK   {name}/{sol_name}: all {len(test_cases)} tests passed")

    return all_passed


def generate(folders):
    """Generate server/problems.json from problem folders."""
    problems = []
    for folder in folders:
        meta, test_cases = load_problem(folder)
        problems.append({
            "id": meta["id"],
            "title": meta["title"],
            "description": meta["description"],
            "difficulty": meta["difficulty"],
            "test_cases": test_cases,
            "starter_code": meta["starter_code"],
        })

    problems.sort(key=lambda p: p["id"])
    with open(OUTPUT_FILE, "w") as f:
        json.dump(problems, f, indent=2)
        f.write("\n")
    print(f"\nGenerated {OUTPUT_FILE} with {len(problems)} problems")


def main():
    parser = argparse.ArgumentParser(description="Build and validate problems")
    parser.add_argument("--validate", action="store_true", help="Only validate solutions")
    parser.add_argument("--generate", action="store_true", help="Only generate server/problems.json")
    parser.add_argument("--problem", type=str, help="Process a single problem folder")
    args = parser.parse_args()

    # Default: both validate and generate
    do_validate = args.validate or (not args.validate and not args.generate)
    do_generate = args.generate or (not args.validate and not args.generate)

    folders = discover_problems(args.problem)

    if do_validate:
        print(f"Validating {len(folders)} problem(s)...\n")
        all_ok = True
        for folder in folders:
            if not validate_problem(folder):
                all_ok = False
        if not all_ok:
            print("\nValidation FAILED")
            sys.exit(1)
        print("\nAll validations passed")

    if do_generate:
        # Always generate from all problems, even if --problem was used for validation
        all_folders = discover_problems()
        generate(all_folders)


if __name__ == "__main__":
    main()
