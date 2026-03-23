"""
Tests for the cmdcode FastAPI server.

Covers:
- Root endpoint
- Auth endpoints: register, challenge, verify
- GET /problems/{id}  — fetch single problem (auth-protected)
- GET /problems       — list all problems (auth-protected)
- POST /submit/{id}   — submit solution, Judge0 mocked (auth-protected)
- Protected route enforcement (401 without valid token)
"""
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from main import app, LANGUAGE_IDS, require_auth
from models import DBSession, DBUser, DBChallenge

# Auth bypass for all non-auth tests (cleared in TestProtectedRoutes)
app.dependency_overrides[require_auth] = lambda: "testuser"

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_upload(code: str, filename: str = "solution.cpp", as_base64: bool = True):
    if as_base64:
        encoded = base64.b64encode(code.encode()).decode()
        return {"file": (filename, encoded, "text/plain;base64")}
    return {"file": (filename, code.encode(), "text/plain")}


def _judge0_response(status_id: int, description: str, stdout: str):
    return {
        "status": {"id": status_id, "description": description},
        "stdout": stdout,
        "time": "0.001",
        "memory": 1024,
    }


def _mock_judge0(mock_client_class, judge0_resp: dict):
    mock_response = MagicMock()
    mock_response.json.return_value = judge0_resp
    mock_response.raise_for_status = MagicMock()

    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_response)

    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)


def _make_ed25519_keypair():
    """Return (private_key, public_key_pem_str)."""
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_key, public_pem


def _sign(private_key, nonce_hex: str) -> str:
    return base64.b64encode(private_key.sign(bytes.fromhex(nonce_hex))).decode()


def _register_user(username: str = "testuser", email: str = "t@example.com", private_key=None):
    """Register a user via the API and return (private_key, pub_pem)."""
    if private_key is None:
        private_key, pub_pem = _make_ed25519_keypair()
    else:
        pub_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    client.post("/auth/register", json={"username": username, "email": email, "public_key": pub_pem})
    return private_key, pub_pem


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

class TestRoot:
    def test_returns_200(self):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_payload_shape(self):
        data = client.get("/").json()
        assert data["project"] == "cmdcode"
        assert data["status"] == "online"
        assert "message" in data


# ---------------------------------------------------------------------------
# GET /problems/{problem_id}
# ---------------------------------------------------------------------------

class TestGetProblem:
    def test_existing_problem_returns_200(self):
        resp = client.get("/problems/1")
        assert resp.status_code == 200

    def test_existing_problem_fields(self):
        data = client.get("/problems/1").json()
        assert data["id"] == 1
        assert data["title"] == "Hello World"
        assert data["difficulty"] == "Easy"
        assert "description" in data
        assert "starter_code" in data
        assert "test_cases" in data

    def test_existing_problem_has_cpp_starter(self):
        data = client.get("/problems/1").json()
        assert "cpp" in data["starter_code"]
        assert data["starter_code"]["cpp"]

    def test_existing_problem_has_test_cases(self):
        data = client.get("/problems/1").json()
        assert len(data["test_cases"]) > 0

    def test_missing_problem_returns_404(self):
        resp = client.get("/problems/9999")
        assert resp.status_code == 404

    def test_missing_problem_error_message(self):
        data = client.get("/problems/9999").json()
        assert "not found" in data["detail"].lower()

    def test_seed_problem_is_accessible(self):
        """Seed data is loaded into DB on startup and accessible via API."""
        data = client.get("/problems/1").json()
        assert data["title"] == "Hello World"


# ---------------------------------------------------------------------------
# GET /problems  (list)
# ---------------------------------------------------------------------------

class TestListProblems:
    def test_list_returns_200(self):
        resp = client.get("/problems")
        assert resp.status_code == 200

    def test_list_returns_array(self):
        data = client.get("/problems").json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_contains_hello_world(self):
        data = client.get("/problems").json()
        assert any(p["title"] == "Hello World" for p in data)

    def test_list_contains_multiple_problems(self):
        data = client.get("/problems").json()
        assert len(data) >= 8

    def test_list_has_mixed_difficulties(self):
        data = client.get("/problems").json()
        difficulties = {p["difficulty"] for p in data}
        assert "Easy" in difficulties
        assert "Medium" in difficulties

    def test_upsert_does_not_duplicate_on_restart(self, db_session):
        """Seeding twice should not create duplicate problems."""
        from main import _sync_problems
        before = client.get("/problems").json()
        _sync_problems(db_session)
        after = client.get("/problems").json()
        assert len(before) == len(after)


# ---------------------------------------------------------------------------
# POST /submit/{problem_id}
# ---------------------------------------------------------------------------

class TestSubmit:
    def test_missing_problem_returns_404(self):
        resp = client.post("/submit/9999", files=make_upload("int main(){}"))
        assert resp.status_code == 404

    def test_unsupported_language_returns_400(self):
        resp = client.post("/submit/1", files=make_upload("puts 'hi'", filename="solution.rb"))
        assert resp.status_code == 400

    def test_invalid_base64_returns_400(self):
        bad_files = {"file": ("solution.cpp", b"not-valid-base64!!!", "text/plain;base64")}
        resp = client.post("/submit/1", files=bad_files)
        assert resp.status_code == 400

    def test_language_ids_cover_common_extensions(self):
        for ext in (".cpp", ".py", ".java", ".js"):
            assert ext in LANGUAGE_IDS

    @patch("main.httpx.AsyncClient")
    def test_accepted_submission(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        resp = client.post("/submit/1", files=make_upload(code))
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["status"] == "Accepted"

    @patch("main.httpx.AsyncClient")
    def test_accepted_submission_result_fields(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        data = client.post("/submit/1", files=make_upload(code)).json()
        assert "filename" in data
        assert "language" in data
        assert "submitted_at" in data
        assert "size_bytes" in data

    @patch("main.httpx.AsyncClient")
    def test_wrong_answer_submission(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(4, "Wrong Answer", "Bad output"))
        code = '#include <iostream>\nint main() { std::cout << "Bad output\\n"; return 0; }\n'
        resp = client.post("/submit/1", files=make_upload(code))
        assert resp.status_code == 200
        assert resp.json()["passed"] is False
        assert resp.json()["status"] == "Wrong"

    @patch("main.httpx.AsyncClient")
    def test_plain_text_upload(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        assert client.post("/submit/1", files=make_upload(code, as_base64=False)).status_code == 200

    @patch("main.httpx.AsyncClient")
    def test_crlf_normalized_in_submission(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        crlf_code = '#include <iostream>\r\nint main() { std::cout << "Hello, World!\\n"; return 0; }\r\n'
        assert client.post("/submit/1", files=make_upload(crlf_code)).status_code == 200

    @patch("main.httpx.AsyncClient")
    def test_submission_persisted_to_db(self, MockClient, db_session):
        """Accepted submissions are written to the submissions table."""
        from models import DBSubmission
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        client.post("/submit/1", files=make_upload(code))
        row = db_session.query(DBSubmission).first()
        assert row is not None
        assert row.passed is True
        assert row.problem_id == 1


# ---------------------------------------------------------------------------
# GET /api/leaderboard
# ---------------------------------------------------------------------------

class TestApiLeaderboard:
    def test_returns_200(self):
        resp = client.get("/api/leaderboard")
        assert resp.status_code == 200

    def test_returns_empty_list_when_no_submissions(self):
        data = client.get("/api/leaderboard").json()
        assert data == []

    def test_returns_users_ranked_by_solved(self, db_session):
        from models import DBSubmission
        # user1 solves 2 problems, user2 solves 1
        for pid in (1, 2):
            db_session.add(DBSubmission(
                problem_id=pid, username="user1", filename="s.py",
                code="x", language=".py", submitted_at="2025-01-01T00:00:00Z",
                size_bytes=1, status="Accepted", passed=True, results=[],
            ))
        db_session.add(DBSubmission(
            problem_id=1, username="user2", filename="s.py",
            code="x", language=".py", submitted_at="2025-01-01T00:00:00Z",
            size_bytes=1, status="Accepted", passed=True, results=[],
        ))
        db_session.commit()
        data = client.get("/api/leaderboard").json()
        assert len(data) == 2
        assert data[0]["username"] == "user1"
        assert data[0]["solved"] == 2
        assert data[0]["rank"] == 1
        assert data[1]["username"] == "user2"
        assert data[1]["solved"] == 1
        assert data[1]["rank"] == 2

    def test_excludes_failed_submissions(self, db_session):
        from models import DBSubmission
        db_session.add(DBSubmission(
            problem_id=1, username="loser", filename="s.py",
            code="x", language=".py", submitted_at="2025-01-01T00:00:00Z",
            size_bytes=1, status="Wrong", passed=False, results=[],
        ))
        db_session.commit()
        data = client.get("/api/leaderboard").json()
        assert all(r["username"] != "loser" for r in data)

    def test_counts_unique_problems_only(self, db_session):
        from models import DBSubmission
        # Same problem solved twice should count as 1
        for _ in range(3):
            db_session.add(DBSubmission(
                problem_id=1, username="repeater", filename="s.py",
                code="x", language=".py", submitted_at="2025-01-01T00:00:00Z",
                size_bytes=1, status="Accepted", passed=True, results=[],
            ))
        db_session.commit()
        data = client.get("/api/leaderboard").json()
        entry = [r for r in data if r["username"] == "repeater"]
        assert len(entry) == 1
        assert entry[0]["solved"] == 1


# ---------------------------------------------------------------------------
# GET /api/problems/public
# ---------------------------------------------------------------------------

class TestApiProblemsPublic:
    def test_returns_200(self):
        resp = client.get("/api/problems/public")
        assert resp.status_code == 200

    def test_returns_list(self):
        data = client.get("/api/problems/public").json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_contains_hello_world(self):
        data = client.get("/api/problems/public").json()
        assert any(p["title"] == "Hello World" for p in data)

    def test_does_not_expose_test_cases(self):
        data = client.get("/api/problems/public").json()
        for p in data:
            assert "test_cases" not in p
            assert "starter_code" not in p

    def test_contains_expected_fields(self):
        data = client.get("/api/problems/public").json()
        for p in data:
            assert "id" in p
            assert "title" in p
            assert "difficulty" in p
            assert "description" in p


# ---------------------------------------------------------------------------
# Auth: register
# ---------------------------------------------------------------------------

class TestAuthRegister:
    def test_register_success(self):
        _, pub_pem = _make_ed25519_keypair()
        resp = client.post("/auth/register", json={
            "username": "alice", "email": "alice@example.com", "public_key": pub_pem,
        })
        assert resp.status_code == 201
        assert resp.json()["username"] == "alice"

    def test_register_stores_user(self, db_session):
        _, pub_pem = _make_ed25519_keypair()
        client.post("/auth/register", json={
            "username": "bob", "email": "bob@example.com", "public_key": pub_pem,
        })
        user = db_session.query(DBUser).filter(DBUser.username == "bob").first()
        assert user is not None
        assert user.email == "bob@example.com"

    def test_register_duplicate_username_returns_409(self):
        _, pub_pem = _make_ed25519_keypair()
        client.post("/auth/register", json={
            "username": "carol", "email": "carol@example.com", "public_key": pub_pem,
        })
        _, pub_pem2 = _make_ed25519_keypair()
        resp = client.post("/auth/register", json={
            "username": "carol", "email": "carol2@example.com", "public_key": pub_pem2,
        })
        assert resp.status_code == 409

    def test_register_invalid_public_key_returns_422(self):
        resp = client.post("/auth/register", json={
            "username": "dave", "email": "dave@example.com", "public_key": "not-a-pem-key",
        })
        assert resp.status_code == 422

    def test_register_short_username_returns_422(self):
        _, pub_pem = _make_ed25519_keypair()
        resp = client.post("/auth/register", json={
            "username": "ab", "email": "ab@example.com", "public_key": pub_pem,
        })
        assert resp.status_code == 422

    def test_register_username_with_special_chars_returns_422(self):
        _, pub_pem = _make_ed25519_keypair()
        resp = client.post("/auth/register", json={
            "username": "bad user!", "email": "x@example.com", "public_key": pub_pem,
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth: challenge
# ---------------------------------------------------------------------------

class TestAuthChallenge:
    def setup_method(self):
        _register_user("testuser")

    def test_challenge_returns_200(self):
        assert client.get("/auth/challenge/testuser").status_code == 200

    def test_challenge_returns_nonce_and_id(self):
        data = client.get("/auth/challenge/testuser").json()
        assert "challenge_id" in data
        assert "nonce" in data
        assert len(data["nonce"]) == 64  # 32 bytes hex

    def test_challenge_stores_in_db(self, db_session):
        cid = client.get("/auth/challenge/testuser").json()["challenge_id"]
        assert db_session.query(DBChallenge).filter(DBChallenge.challenge_id == cid).first() is not None

    def test_challenge_unknown_user_returns_404(self):
        assert client.get("/auth/challenge/nobody").status_code == 404


# ---------------------------------------------------------------------------
# Auth: verify (full end-to-end challenge-response)
# ---------------------------------------------------------------------------

class TestAuthVerify:
    def setup_method(self):
        self.private_key, _ = _register_user("vera")

    def _get_challenge(self):
        data = client.get("/auth/challenge/vera").json()
        return data["challenge_id"], data["nonce"]

    def test_verify_valid_signature_returns_token(self):
        cid, nonce = self._get_challenge()
        resp = client.post("/auth/verify", json={
            "username": "vera", "challenge_id": cid,
            "signature": _sign(self.private_key, nonce),
        })
        assert resp.status_code == 200
        assert "token" in resp.json()
        assert "expires_at" in resp.json()

    def test_verify_stores_session(self, db_session):
        cid, nonce = self._get_challenge()
        client.post("/auth/verify", json={
            "username": "vera", "challenge_id": cid,
            "signature": _sign(self.private_key, nonce),
        })
        assert db_session.query(DBSession).count() == 1

    def test_verify_wrong_signature_returns_401(self):
        cid, nonce = self._get_challenge()
        bad_sig = base64.b64encode(b"\x00" * 64).decode()
        assert client.post("/auth/verify", json={
            "username": "vera", "challenge_id": cid, "signature": bad_sig,
        }).status_code == 401

    def test_verify_replay_rejected(self):
        cid, nonce = self._get_challenge()
        sig = _sign(self.private_key, nonce)
        client.post("/auth/verify", json={"username": "vera", "challenge_id": cid, "signature": sig})
        assert client.post("/auth/verify", json={
            "username": "vera", "challenge_id": cid, "signature": sig,
        }).status_code == 401

    def test_verify_unknown_challenge_returns_401(self):
        assert client.post("/auth/verify", json={
            "username": "vera",
            "challenge_id": "00000000-0000-0000-0000-000000000000",
            "signature": base64.b64encode(b"\x00" * 64).decode(),
        }).status_code == 401

    def test_verify_expired_challenge_returns_401(self, db_session):
        from datetime import timedelta
        cid, nonce = self._get_challenge()
        # Backdate the challenge in the DB
        row = db_session.query(DBChallenge).filter(DBChallenge.challenge_id == cid).first()
        from datetime import datetime, timezone
        row.expires_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        db_session.commit()
        assert client.post("/auth/verify", json={
            "username": "vera", "challenge_id": cid,
            "signature": _sign(self.private_key, nonce),
        }).status_code == 401


# ---------------------------------------------------------------------------
# Protected route enforcement
# ---------------------------------------------------------------------------

class TestProtectedRoutes:
    """Ensure protected routes return 401 when no valid token is provided."""

    def setup_method(self):
        app.dependency_overrides.pop(require_auth, None)

    def teardown_method(self):
        app.dependency_overrides[require_auth] = lambda: "testuser"

    def test_get_problem_without_token_returns_401(self):
        assert client.get("/problems/1").status_code == 401

    def test_list_problems_without_token_returns_401(self):
        assert client.get("/problems").status_code == 401

    def test_submit_without_token_returns_401(self):
        assert client.post("/submit/1", files=make_upload("int main(){}")).status_code == 401

    def test_get_problem_with_valid_token_returns_200(self, db_session):
        from datetime import datetime, timedelta, timezone
        token = "validtoken123"
        db_session.add(DBUser(
            username="tempuser", email="t@t.com",
            public_key_pem="x", created_at=datetime.now(timezone.utc).isoformat(),
        ))
        db_session.add(DBSession(
            token=token, username="tempuser",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        ))
        db_session.commit()
        assert client.get("/problems/1", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    def test_get_problem_with_expired_token_returns_401(self, db_session):
        from datetime import datetime, timedelta, timezone
        token = "expiredtoken"
        db_session.add(DBUser(
            username="tempuser2", email="t2@t.com",
            public_key_pem="x", created_at=datetime.now(timezone.utc).isoformat(),
        ))
        db_session.add(DBSession(
            token=token, username="tempuser2",
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        ))
        db_session.commit()
        assert client.get("/problems/1", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ---------------------------------------------------------------------------
# Security: rate limiting
# ---------------------------------------------------------------------------

class TestSubmissionRateLimit:
    """Exponential backoff rate limiting on POST /submit."""

    @patch("main.httpx.AsyncClient")
    def test_second_submission_too_fast_returns_429(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        files = make_upload(code)
        # First submission succeeds
        resp1 = client.post("/submit/1", files=files)
        assert resp1.status_code == 200
        # Immediate second submission should be rate limited
        resp2 = client.post("/submit/1", files=files)
        assert resp2.status_code == 429

    @patch("main.httpx.AsyncClient")
    def test_rate_limit_response_has_retry_after_header(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        files = make_upload(code)
        client.post("/submit/1", files=files)
        resp = client.post("/submit/1", files=files)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


class TestChallengeRateLimit:
    """Max challenge requests per user per window."""

    def test_challenge_rate_limit(self):
        _, pub_pem = _make_ed25519_keypair()
        client.post("/auth/register", json={
            "username": "ratelimituser", "email": "rl@example.com", "public_key": pub_pem,
        })
        from main import CHALLENGE_RATE_LIMIT
        # Exhaust the limit
        for _ in range(CHALLENGE_RATE_LIMIT):
            client.get("/auth/challenge/ratelimituser")
        # Next one should be rejected
        resp = client.get("/auth/challenge/ratelimituser")
        assert resp.status_code == 429


class TestVerifyFailRateLimit:
    """Lock out after too many failed verifications."""

    def test_verify_lockout_after_too_many_failures(self):
        _, pub_pem = _make_ed25519_keypair()
        client.post("/auth/register", json={
            "username": "lockoutuser", "email": "lo@example.com", "public_key": pub_pem,
        })
        from main import VERIFY_FAIL_LIMIT
        bad_sig = base64.b64encode(b"\x00" * 64).decode()
        for _ in range(VERIFY_FAIL_LIMIT):
            # Each attempt needs a fresh challenge
            data = client.get("/auth/challenge/lockoutuser").json()
            client.post("/auth/verify", json={
                "username": "lockoutuser",
                "challenge_id": data["challenge_id"],
                "signature": bad_sig,
            })
        # After VERIFY_FAIL_LIMIT failures the user should be locked out
        data = client.get("/auth/challenge/lockoutuser").json()
        resp = client.post("/auth/verify", json={
            "username": "lockoutuser",
            "challenge_id": data["challenge_id"],
            "signature": bad_sig,
        })
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Security: file upload limits and filename sanitization
# ---------------------------------------------------------------------------

class TestUploadLimits:
    def test_oversized_file_returns_413(self):
        from main import MAX_UPLOAD_BYTES
        oversized = "x" * (MAX_UPLOAD_BYTES + 1)
        files = {"file": ("solution.cpp", oversized.encode(), "text/plain")}
        resp = client.post("/submit/1", files=files)
        assert resp.status_code == 413

    @patch("main.httpx.AsyncClient")
    def test_path_traversal_filename_sanitized(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        files = {"file": ("../../etc/passwd.cpp", code.encode(), "text/plain")}
        resp = client.post("/submit/1", files=files)
        assert resp.status_code == 200
        # The stored filename must not contain directory separators
        assert "/" not in resp.json()["filename"]
        assert "\\" not in resp.json()["filename"]

    @patch("main.httpx.AsyncClient")
    def test_null_byte_in_filename_sanitized(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))
        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        files = {"file": ("solution\x00evil.cpp", code.encode(), "text/plain")}
        resp = client.post("/submit/1", files=files)
        assert resp.status_code == 200
        assert "\x00" not in resp.json()["filename"]


# ---------------------------------------------------------------------------
# Security: security headers middleware
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_root_has_nosniff_header(self):
        resp = client.get("/")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_root_has_x_frame_options(self):
        resp = client.get("/")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_root_has_referrer_policy(self):
        resp = client.get("/")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_root_has_cache_control(self):
        resp = client.get("/")
        assert resp.headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# GET /users/{username}/stats
# ---------------------------------------------------------------------------

def _add_submission(db, username, problem_id, passed, language=".cpp"):
    from models import DBSubmission
    db.add(DBSubmission(
        problem_id=problem_id, username=username, filename=f"s{language}",
        code="x", language=language, submitted_at="2025-01-01T00:00:00Z",
        size_bytes=1, status="Accepted" if passed else "Wrong", passed=passed, results=[],
    ))
    db.commit()


class TestUserStats:
    def test_stats_returns_200_for_own_user(self):
        resp = client.get("/users/testuser/stats")
        assert resp.status_code == 200

    def test_stats_zero_when_no_submissions(self):
        data = client.get("/users/testuser/stats").json()
        assert data["total_submissions"] == 0
        assert data["accepted_submissions"] == 0
        assert data["unique_problems_solved"] == 0
        assert data["accuracy_rate"] == 0.0
        assert data["favorite_language"] is None
        assert data["rank"] is None

    def test_stats_counts_submissions(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True)
        _add_submission(db_session, "testuser", 1, passed=False)
        data = client.get("/users/testuser/stats").json()
        assert data["total_submissions"] == 2
        assert data["accepted_submissions"] == 1

    def test_stats_counts_unique_problems_solved(self, db_session):
        # Same problem solved twice still counts as 1
        _add_submission(db_session, "testuser", 1, passed=True)
        _add_submission(db_session, "testuser", 1, passed=True)
        _add_submission(db_session, "testuser", 2, passed=True)
        data = client.get("/users/testuser/stats").json()
        assert data["unique_problems_solved"] == 2

    def test_stats_accuracy_rate(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True)
        _add_submission(db_session, "testuser", 2, passed=False)
        data = client.get("/users/testuser/stats").json()
        assert data["accuracy_rate"] == 50.0

    def test_stats_favorite_language(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True, language=".py")
        _add_submission(db_session, "testuser", 2, passed=True, language=".py")
        _add_submission(db_session, "testuser", 3, passed=True, language=".cpp")
        data = client.get("/users/testuser/stats").json()
        assert data["favorite_language"] == ".py"

    def test_stats_rank_assigned(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True)
        data = client.get("/users/testuser/stats").json()
        assert data["rank"] == 1

    def test_stats_forbidden_for_other_user(self):
        resp = client.get("/users/otheruser/stats")
        assert resp.status_code == 403

    def test_stats_requires_auth(self):
        app.dependency_overrides.pop(require_auth, None)
        try:
            resp = client.get("/users/testuser/stats")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides[require_auth] = lambda: "testuser"


# ---------------------------------------------------------------------------
# GET /users/{username}/history
# ---------------------------------------------------------------------------

class TestUserHistory:
    def test_history_returns_200(self):
        resp = client.get("/users/testuser/history")
        assert resp.status_code == 200

    def test_history_empty_when_no_submissions(self):
        data = client.get("/users/testuser/history").json()
        assert data == []

    def test_history_returns_submissions(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True)
        data = client.get("/users/testuser/history").json()
        assert len(data) == 1
        entry = data[0]
        assert entry["problem_id"] == 1
        assert entry["verdict"] == "Accepted"
        assert entry["language"] == ".cpp"
        assert "submission_id" in entry
        assert "submitted_at" in entry
        assert "size_bytes" in entry

    def test_history_wrong_answer_verdict(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=False)
        data = client.get("/users/testuser/history").json()
        assert data[0]["verdict"] == "Wrong Answer"

    def test_history_includes_problem_title(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True)
        data = client.get("/users/testuser/history").json()
        assert data[0]["problem_title"] == "Hello World"

    def test_history_ordered_most_recent_first(self, db_session):
        _add_submission(db_session, "testuser", 1, passed=True)
        _add_submission(db_session, "testuser", 2, passed=False)
        data = client.get("/users/testuser/history").json()
        assert data[0]["submission_id"] > data[1]["submission_id"]

    def test_history_limit_param(self, db_session):
        for pid in range(1, 6):
            _add_submission(db_session, "testuser", pid, passed=True)
        data = client.get("/users/testuser/history?limit=3").json()
        assert len(data) == 3

    def test_history_limit_capped_at_100(self, db_session):
        resp = client.get("/users/testuser/history?limit=9999")
        assert resp.status_code == 200

    def test_history_forbidden_for_other_user(self):
        resp = client.get("/users/otheruser/history")
        assert resp.status_code == 403

    def test_history_requires_auth(self):
        app.dependency_overrides.pop(require_auth, None)
        try:
            resp = client.get("/users/testuser/history")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides[require_auth] = lambda: "testuser"
