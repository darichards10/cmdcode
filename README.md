# cmdcode

A terminal-first coding practice platform. Download problems, write solutions in your editor, and get instant verdicts — all from the command line.

```
cmdcode list                      # browse available problems
cmdcode get 1                     # download problem + starter code
vim solution.cpp                  # write your solution
cmdcode submit 1                  # get instant verdict
```

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Workflow](#workflow)
- [Configuration](#configuration)
- [Running Locally (Self-Hosted)](#running-locally-self-hosted)
- [Development](#development)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)

---

## Installation

**Recommended (isolated environment):**

```bash
pipx install cmdcode
```

**Alternative:**

```bash
pip install --user cmdcode
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**Requirements:** Python 3.9+

Verify the install:

```bash
cmdcode --version
```

---

## Quick Start

```bash
# 1. See what problems are available
cmdcode list

# 2. Download a problem (creates a folder with README + starter code)
cmdcode get 1

# 3. Open the generated starter file
cd 0001-hello-world/
vim solution.cpp

# 4. Submit and get your verdict
cmdcode submit 1
```

---

## Commands

### `cmdcode list`

Lists all available problems with their ID, title, and difficulty.

```
 ID   Title         Difficulty
 1    Hello World   Easy
```

Difficulty is color-coded: green = Easy, yellow = Medium, red = Hard.

---

### `cmdcode get <PROBLEM_ID>`

Downloads a problem and generates a local workspace folder.

```bash
cmdcode get 1
```

Creates `{ID:04d}-{slugified-title}/` (e.g. `0001-hello-world/`) containing:

- `README.md` — problem statement, constraints, and examples
- `solution.cpp` — starter code with function signature

---

### `cmdcode submit <PROBLEM_ID> [FILE]`

Submits a solution file to the judge.

```bash
cmdcode submit 1               # defaults to solution.cpp in current directory
cmdcode submit 1 my_solution.cpp
```

The judge runs your code against all test cases and returns a verdict table:

```
 Submission ID   Problem ID   File           Language   Verdict    Time    Memory
 abc123          1            solution.cpp   C++        Accepted   0.01s   1.2 MB
```

**Verdict values:**
- `Accepted` — all test cases passed
- `Wrong Answer` — output did not match expected

**Supported languages** (detected by file extension):

| Extension | Language   |
|-----------|------------|
| `.cpp`    | C++        |
| `.c`      | C          |
| `.py`     | Python     |
| `.java`   | Java       |
| `.js`     | JavaScript |
| `.ts`     | TypeScript |
| `.go`     | Go         |
| `.rs`     | Rust       |

---

### `cmdcode version`

Prints the current CLI version.

```bash
cmdcode version
cmdcode --version
cmdcode -v
```

---

## Workflow

A typical practice session:

```bash
# Browse problems
cmdcode list

# Pick one and download it
cmdcode get 3
cd 0003-problem-name/

# Read the problem
cat README.md

# Edit your solution
vim solution.cpp

# Submit
cmdcode submit 3

# Iterate until Accepted
```

---

## Configuration

The CLI connects to a hosted server by default (`http://98.81.154.236:8000`). No configuration is required to use the hosted version.

If you're self-hosting the server, set the `SERVER_URL` environment variable:

```bash
export SERVER_URL=http://localhost:8000
cmdcode list
```

---

## Running Locally (Self-Hosted)

The full stack requires Docker and Docker Compose.

> **Note:** Judge0 worker containers must run on Ubuntu 20 or any OS with cgroups v1.

**Start all services:**

```bash
docker-compose up
```

This starts:
- `cmdcode-server` — FastAPI backend on port 8000
- `judge0-server` — Code execution engine on port 2358
- `judge0-worker` — Execution workers
- `postgres` — Judge0 database
- `redis` — Judge0 cache

**Point the CLI at your local server:**

```bash
export SERVER_URL=http://localhost:8000
cmdcode list
```

**Server environment variables:**

| Variable    | Default                    | Description              |
|-------------|----------------------------|--------------------------|
| `APP_PORT`  | `8000`                     | Server port              |
| `JUDGE0_URL`| `http://judge0:2358`       | Judge0 API endpoint      |

---

## Development

**Clone the repo:**

```bash
git clone https://github.com/darichards10/cmdcode.git
cd cmdcode
```

**Install development dependencies:**

```bash
pip install -r requirements-dev.txt
```

**Run the server locally (without Docker):**

```bash
cd server
uvicorn main:app --reload
```

**Run tests:**

```bash
pytest                   # all tests
pytest -v                # verbose
pytest tests/cli/        # CLI tests only
pytest tests/server/     # server tests only
```

---

## Project Structure

```
cmdcode/
├── cli/                  # Python CLI package (published to PyPI)
│   ├── pyproject.toml
│   └── src/cmdcode/
│       └── cli.py        # Commands: get, submit, list, version
├── server/               # FastAPI backend
│   ├── main.py           # API endpoints and Judge0 integration
│   ├── requirements.txt
│   └── Dockerfile
├── judge/                # Judge0 Docker Compose config
│   └── docker-compose.yml
├── tests/
│   ├── cli/              # CLI unit tests
│   └── server/           # API tests
├── docker-compose.yml    # Full stack (server + judge)
└── requirements-dev.txt  # Dev dependencies
```

---

## Roadmap

- [ ] Website with problem browser
- [ ] User identity / authentication
- [ ] Daily challenge generation
- [ ] Expanded problem set
- [ ] Additional language support

---

## License

MIT © Drew Richards
