# Auth Implementation Plan — SSH-Style Challenge-Response

## Design Summary

- **Key source:** cmdcode generates its own Ed25519 keypair in `~/.cmdcode/`
- **Session caching:** challenge-response runs once, server issues a 24h token stored locally
- **Email:** stored as metadata, not verified
- **Keys per account:** one key per account

---

## New File Layout (`~/.cmdcode/`)

```
~/.cmdcode/
├── id_ed25519        # Ed25519 private key (PEM, chmod 600)
├── id_ed25519.pub    # Ed25519 public key (PEM)
├── config.json       # { username, email, server_url }
└── session.json      # { token, expires_at }
```

---

## Full Auth Flow

```
cmdcode register
  ├── prompt: username, email
  ├── generate Ed25519 keypair → ~/.cmdcode/id_ed25519 + id_ed25519.pub
  ├── chmod 600 on private key
  ├── save ~/.cmdcode/config.json
  └── POST /auth/register { username, email, public_key_pem }

cmdcode submit 1  (or any protected command)
  ├── get_auth_token()
  │     ├── read ~/.cmdcode/session.json
  │     ├── if token exists and not expired → return token
  │     └── else → challenge-response:
  │           ├── GET /auth/challenge/{username}
  │           │     └── server returns { challenge_id, nonce }
  │           ├── sign nonce with private key (Ed25519)
  │           ├── POST /auth/verify { username, challenge_id, signature_b64 }
  │           │     └── server verifies signature, returns { token, expires_at }
  │           └── save to ~/.cmdcode/session.json
  └── attach Authorization: Bearer {token} to request
```

---

## Phase 1 — CLI Changes (`cli/src/cmdcode/cli.py`)

### 1.1 New dependency
Add `cryptography>=41.0` to `cli/pyproject.toml`.

### 1.2 New helper: `get_cmdcode_dir()`
Returns `~/.cmdcode/` as a `Path`, creates it if missing.

### 1.3 New command: `cmdcode register`
```
cmdcode register
```
Steps:
1. Check if `~/.cmdcode/id_ed25519` already exists — if so, print error and exit
2. Prompt for `username` and `email` (use `typer.prompt`)
3. Generate Ed25519 private key via `cryptography` library
4. Write private key PEM → `~/.cmdcode/id_ed25519`, `chmod 600`
5. Write public key PEM → `~/.cmdcode/id_ed25519.pub`
6. Write `~/.cmdcode/config.json` with `{ username, email, server_url }`
7. POST `/auth/register` with `{ username, email, public_key }` (public key as PEM string)
8. Print success: key fingerprint + location

### 1.4 New internal helper: `get_auth_token() -> str`
Called before any protected command. Returns a valid Bearer token.

```python
def get_auth_token() -> str:
    # 1. Load session.json — if token not expired, return it
    # 2. Load config.json for username
    # 3. Load private key from id_ed25519
    # 4. GET /auth/challenge/{username} → { challenge_id, nonce }
    # 5. Sign nonce bytes with private key
    # 6. POST /auth/verify { username, challenge_id, signature_b64 } → { token, expires_at }
    # 7. Save to session.json
    # 8. Return token
```

### 1.5 Attach auth to protected commands
- `submit`: add `Authorization: Bearer {token}` header
- `get`: add header
- `list`: add header

### 1.6 New command: `cmdcode whoami`
Prints the currently registered username, email, and key fingerprint from `config.json` + `id_ed25519.pub`.

---

## Phase 2 — Server Changes (`server/main.py`)

### 2.1 New dependency
Add `cryptography>=41.0` to `server/requirements.txt`.

### 2.2 New in-memory stores
```python
USERS_DB: dict      # username -> { username, email, public_key_pem, created_at }
CHALLENGES_DB: dict # challenge_id -> { username, nonce, expires_at }   (60s TTL)
SESSIONS_DB: dict   # token -> { username, expires_at }                  (24h TTL)
```

### 2.3 New Pydantic models
```python
class RegisterRequest(BaseModel):
    username: str
    email: str
    public_key: str   # PEM string

class ChallengeResponse(BaseModel):
    challenge_id: str
    nonce: str        # hex-encoded random bytes

class VerifyRequest(BaseModel):
    username: str
    challenge_id: str
    signature: str    # base64-encoded signature

class TokenResponse(BaseModel):
    token: str
    expires_at: str
```

### 2.4 New endpoints

**`POST /auth/register`**
1. Validate username is alphanumeric, 3–20 chars
2. Check username not already taken
3. Parse and validate the PEM public key (must be Ed25519)
4. Store in `USERS_DB`
5. Return `{ message: "registered", username }`

**`GET /auth/challenge/{username}`**
1. Look up username in `USERS_DB` — 404 if not found
2. Generate `challenge_id` (UUID) and `nonce` (32 random bytes, hex-encoded)
3. Store in `CHALLENGES_DB` with 60-second expiry
4. Return `{ challenge_id, nonce }`

**`POST /auth/verify`**
1. Look up `challenge_id` in `CHALLENGES_DB` — 404 if missing or expired
2. Look up username — 404 if not found
3. Verify the nonce signature using stored public key (Ed25519)
4. Delete challenge from `CHALLENGES_DB` (prevent replay)
5. Generate opaque token (UUID or `secrets.token_hex(32)`)
6. Store in `SESSIONS_DB` with 24h expiry
7. Return `{ token, expires_at }`

### 2.5 Auth dependency for protected routes
```python
def require_auth(authorization: str = Header(...)) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    session = SESSIONS_DB.get(token)
    if not session or datetime.utcnow() > session["expires_at"]:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session["username"]
```

Apply to `GET /problems/{id}`, `POST /submit/{id}`, `GET /problems`.

---

## Phase 3 — Tests

### 3.1 New CLI tests (`tests/cli/test_cli.py`)
- `TestRegister`: keypair generated, config saved, server called, error on duplicate key
- `TestAuthToken`: valid cached token returned, expired token triggers re-auth, missing token triggers auth
- `TestProtectedCommands`: submit/get/list include auth header

### 3.2 New server tests (`tests/server/test_api.py`)
- `TestRegister`: success, duplicate username, invalid public key
- `TestChallenge`: valid username, unknown username
- `TestVerify`: valid signature accepted, wrong signature rejected, expired challenge rejected, replay rejected
- `TestProtectedRoutes`: 401 without token, 401 with expired token, 200 with valid token

---

## Implementation Order

1. Server: data models + `/auth/register` + `/auth/challenge` + `/auth/verify`
2. Server: auth dependency + protect existing endpoints
3. CLI: `get_cmdcode_dir()` + `cmdcode register`
4. CLI: `get_auth_token()` helper
5. CLI: attach auth headers to `submit`, `get`, `list`
6. CLI: `cmdcode whoami`
7. Tests: server auth tests
8. Tests: CLI auth tests
9. Update README with new auth commands
