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
- [Contributing](#contributing)
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

The CLI connects to a hosted server by default. No configuration is required to use the hosted version.

If you're self-hosting the server, set the `SERVER_URL` environment variable:

```bash
export SERVER_URL=http://localhost:8000
cmdcode list
```

---

## Running Locally (Self-Hosted)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/install/) v2 (included with Docker Desktop)
- Linux with **cgroups v1** required for Judge0 workers (see note below)

> **cgroups v1 note:** Judge0's sandbox requires cgroups v1. On modern Ubuntu/Debian systems you can enable it by adding `systemd.unified_cgroup_hierarchy=0` to your kernel boot parameters (edit `/etc/default/grub`, then run `update-grub` and reboot). On WSL2, cgroups v2 is not supported — use a Linux VM instead.

### 1. Configure Judge0

Copy the example config and set required secrets:

```bash
cp judge/judge0.conf.example judge/judge0.conf
```

Open `judge/judge0.conf` and set at minimum:

```
REDIS_PASSWORD=your_redis_password_here
POSTGRES_PASSWORD=your_postgres_password_here
```

### 2. Create a `.env` file

Create a `.env` file in the project root:

```bash
APP_PORT=8000
JUDGE0_URL=http://judge0:2358
CORS_ORIGINS=http://localhost:3000
```

### 3. Start all services

```bash
docker-compose up --build
```

This starts:
- `cmdcode-server` — FastAPI backend on port 8000
- `cmdcode-frontend` — Next.js frontend on port 3000
- `judge0-server` — Code execution engine on port 2358
- `judge0-worker` — Execution workers
- `judge0-db` — PostgreSQL database for Judge0
- `judge0-redis` — Redis cache for Judge0

Wait about 30 seconds for Judge0 to initialize before submitting code.

### 4. Point the CLI at your local server

```bash
export SERVER_URL=http://localhost:8000
cmdcode list
```

### 5. Verify services are running

```bash
# Check server health
curl http://localhost:8000/problems

# Check Judge0
curl http://localhost:2358/system_info

# Frontend
open http://localhost:3000
```

### Server environment variables

| Variable        | Default                              | Description                      |
|-----------------|--------------------------------------|----------------------------------|
| `APP_PORT`      | `8000`                               | Server port                      |
| `JUDGE0_URL`    | `http://judge0:2358`                 | Judge0 API endpoint              |
| `CORS_ORIGINS`  | `http://localhost:3000,...`          | Allowed CORS origins             |
| `DATABASE_URL`  | `sqlite:////data/cmdcode.db`         | SQLite database path (in volume) |

---

## Development

### Prerequisites

- Python 3.9+
- Node.js 18+ (for frontend)

### 1. Clone and set up Python environment

```bash
git clone https://github.com/darichards10/cmdcode.git
cd cmdcode

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
```

### 2. Install the CLI in editable mode

```bash
pip install -e cli/
```

Changes to `cli/src/cmdcode/cli.py` are reflected immediately without reinstalling.

### 3. Run the server

```bash
cd server
uvicorn main:app --reload
```

The server starts at `http://localhost:8000`. The `--reload` flag restarts it automatically when you edit Python files.

Point your local CLI at it:

```bash
export SERVER_URL=http://localhost:8000
cmdcode list
```

> **Note:** Running the server outside Docker means code submissions require a running Judge0 instance. Start just the judge services with:
> ```bash
> docker-compose up judge0-server judge0-worker judge0-db judge0-redis
> ```
> Then set `JUDGE0_URL=http://localhost:2358` before starting the server.

### 4. Run the frontend (optional)

```bash
cd frontend
npm install
npm run dev
```

The frontend starts at `http://localhost:3000`.

### 5. Run tests

```bash
pytest                    # all tests
pytest -v                 # verbose output
pytest tests/cli/         # CLI tests only
pytest tests/server/      # server tests only
pytest -k test_submit     # run tests matching a name pattern
```

Tests use mock HTTP responses — no running server or Judge0 instance is required.

---

## Project Structure

```
cmdcode/
├── cli/                        # Python CLI package (published to PyPI)
│   ├── pyproject.toml
│   └── src/cmdcode/
│       └── cli.py              # Commands: get, submit, list, version
├── server/                     # FastAPI backend
│   ├── main.py                 # API endpoints and Judge0 integration
│   ├── database.py             # SQLAlchemy setup
│   ├── models.py               # ORM models
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # Next.js web interface
│   ├── src/
│   ├── package.json
│   └── Dockerfile
├── judge/                      # Judge0 Docker Compose config
│   ├── docker-compose.yml
│   ├── docker-entrypoint.sh
│   └── judge0.conf.example     # Copy to judge0.conf and fill in secrets
├── problems/                   # Problem definitions
│   ├── NNN-problem-slug/       # One folder per problem
│   │   ├── problem.json
│   │   ├── tests/
│   │   └── solutions/
│   ├── build.py                # Validate problems and generate problems.json
│   └── README.md               # Guide for adding new problems
├── tests/
│   ├── cli/                    # CLI unit tests
│   └── server/                 # API tests
├── docker-compose.yml          # Full stack (server + frontend + judge)
├── requirements-dev.txt        # Dev dependencies
└── pytest.ini
```

---

## Contributing

Contributions are welcome. There are two main ways to contribute:

### Contributing Problems

See [`problems/README.md`](problems/README.md) for a full guide on adding coding problems, including folder structure, `problem.json` format, test case requirements, and how to validate locally before opening a PR.

### Contributing Code

There are three areas of the codebase you can contribute to:

**CLI (`cli/src/cmdcode/cli.py`)**
- New commands or flags
- Output formatting improvements
- Bug fixes

**Server (`server/`)**
- New API endpoints (`main.py`)
- Database model changes (`models.py`, `database.py`)
- Judge0 integration improvements

**Frontend (`frontend/src/`)**
- UI components and pages
- Bug fixes

#### Steps

1. **Fork and clone** the repository.

2. **Create a branch** from `main`:
   ```bash
   git checkout -b my-feature
   ```

3. **Set up the dev environment** (see [Development](#development)).

4. **Make your changes** and add or update tests in `tests/cli/` or `tests/server/` as appropriate.

5. **Run tests** to make sure everything passes:
   ```bash
   pytest
   ```

6. **Commit** with a descriptive message:
   ```bash
   git commit -m "Add X feature to Y component"
   ```

7. **Open a pull request** against `main`. Describe what the change does and include any relevant context.

#### Guidelines

- Keep pull requests focused on a single change.
- New server endpoints should have corresponding tests in `tests/server/`.
- New CLI commands should have corresponding tests in `tests/cli/`.
- Do not commit `judge/judge0.conf` — it contains secrets.

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
