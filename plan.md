# Backend Security Hardening Plan

## Current State

FastAPI app with Ed25519 challenge-response auth, SQLAlchemy ORM, Judge0 code execution.
Auth is solid (crypto-signed, replay-protected), but **no rate limiting** and several other gaps.

---

## 1. Exponential Backoff Rate Limiting on Submissions

**Problem:** `/submit/{problem_id}` has no throttle — a user can spam submissions, overloading Judge0.

**Approach:** Per-user in-memory rate limiter with exponential cooldown tracked in the DB.

- Track each user's recent submission timestamps in a new `DBRateLimit` model
- After each submission, compute a cooldown: `base * 2^(n-1)` where `n` = submissions in the window
  - Base cooldown: **2 seconds**
  - Window: **5 minutes** (submissions older than this don't count)
  - Max cooldown cap: **120 seconds**
- Before accepting a submission, check if the user's cooldown has elapsed since their last submission
- Return `429 Too Many Requests` with a `Retry-After` header if they submit too early
- Cooldown resets naturally as the window slides — infrequent submitters face no delay

**Files:** `server/main.py`, `server/models.py`

---

## 2. Auth Endpoint Rate Limiting

**Problem:** `/auth/challenge/{username}` and `/auth/verify` have no limits — brute-force and DoS vectors.

**Approach:** IP-based + username-based rate limiting for auth endpoints.

- `/auth/register`: Max **5 registrations per IP per hour** (in-memory counter)
- `/auth/challenge/{username}`: Max **10 challenges per username per 5 minutes** (DB query count)
- `/auth/verify`: Max **5 failed verifications per username per 15 minutes** — lockout with exponential backoff

**Files:** `server/main.py`

---

## 3. File Upload Size Limit

**Problem:** No cap on uploaded file size — memory exhaustion risk.

**Approach:**
- Hard limit of **1 MB** on uploaded code files
- Check `len(raw_bytes)` immediately after `file.read()`, reject with `413` if exceeded

**Files:** `server/main.py`

---

## 4. Expired Session / Challenge Cleanup

**Problem:** Expired sessions and challenges accumulate in the DB forever.

**Approach:**
- Add a background task (FastAPI `BackgroundTasks`) that purges expired records
- Run cleanup on each auth request (lightweight: single DELETE query)

**Files:** `server/main.py`

---

## 5. Security Headers Middleware

**Problem:** No security headers set — missing basic hardening.

**Approach:** Add middleware that sets:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Cache-Control: no-store` on API responses

**Files:** `server/main.py`

---

## 6. Filename Sanitization

**Problem:** Filename from upload is stored as-is — could contain path traversal or special chars.

**Approach:**
- Strip directory components (`os.path.basename`)
- Reject filenames with null bytes or control characters

**Files:** `server/main.py`

---

## 7. Tests

Add tests covering:
- Submission rate limiting (exponential backoff behavior, 429 responses)
- Auth rate limiting (challenge flood, verify brute-force)
- File size limit enforcement
- Filename sanitization
- Security headers presence

**Files:** `tests/server/test_api.py`

---

## Implementation Order

1. Models (`DBRateLimit`) + DB migration
2. Submission rate limiting with exponential backoff
3. Auth endpoint rate limiting
4. File upload size limit + filename sanitization
5. Expired record cleanup
6. Security headers middleware
7. Tests for all of the above
