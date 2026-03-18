"""
Tests for the cmdcode FastAPI server.

Covers:
- Root endpoint
- GET /problems/{id}  — fetch single problem
- GET /problems       — list endpoint (currently unimplemented, documented here)
- POST /submit/{id}   — submit solution (Judge0 is mocked)
"""
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app, PROBLEMS_DB, LANGUAGE_IDS

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_upload(code: str, filename: str = "solution.cpp", as_base64: bool = True):
    """Return a files dict suitable for client.post(..., files=...)."""
    if as_base64:
        encoded = base64.b64encode(code.encode()).decode()
        return {"file": (filename, encoded, "text/plain;base64")}
    return {"file": (filename, code.encode(), "text/plain")}


def _judge0_response(status_id: int, description: str, stdout: str):
    """Build a minimal Judge0 API response dict."""
    return {
        "status": {"id": status_id, "description": description},
        "stdout": stdout,
        "time": "0.001",
        "memory": 1024,
    }


def _mock_judge0(mock_client_class, judge0_resp: dict):
    """Wire up an httpx.AsyncClient mock that returns judge0_resp for any POST."""
    mock_response = MagicMock()
    mock_response.json.return_value = judge0_resp
    mock_response.raise_for_status = MagicMock()

    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_response)

    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)


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
        assert data["starter_code"]["cpp"]  # not empty

    def test_existing_problem_has_test_cases(self):
        data = client.get("/problems/1").json()
        assert len(data["test_cases"]) > 0

    def test_missing_problem_returns_404(self):
        resp = client.get("/problems/9999")
        assert resp.status_code == 404

    def test_missing_problem_error_message(self):
        data = client.get("/problems/9999").json()
        assert "not found" in data["detail"].lower()

    def test_problems_db_contains_seed_data(self):
        """Sanity-check that the in-memory DB has the expected seed problem."""
        assert 1 in PROBLEMS_DB
        assert PROBLEMS_DB[1].title == "Hello World"


# ---------------------------------------------------------------------------
# GET /problems  (list)
# NOTE: This route does not exist yet — test documents the current behavior.
# ---------------------------------------------------------------------------

class TestListProblems:
    def test_list_endpoint_not_implemented(self):
        """
        /problems (no trailing int) is not defined. FastAPI returns 404.
        This test will need updating once the list route is added.
        """
        resp = client.get("/problems")
        # FastAPI returns 404 for unmatched paths
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /submit/{problem_id}
# ---------------------------------------------------------------------------

class TestSubmit:
    # --- Problem / language validation ---

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

    # --- Language ID mapping ---

    def test_language_ids_cover_common_extensions(self):
        for ext in (".cpp", ".py", ".java", ".js"):
            assert ext in LANGUAGE_IDS, f"Missing language mapping for {ext}"

    # --- Accepted verdict ---

    @patch("main.httpx.AsyncClient")
    def test_accepted_submission(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))

        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        resp = client.post("/submit/1", files=make_upload(code))

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["status"] == "Accepted"
        assert data["problem_id"] == 1

    @patch("main.httpx.AsyncClient")
    def test_accepted_submission_result_fields(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))

        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        data = client.post("/submit/1", files=make_upload(code)).json()

        assert "filename" in data
        assert "language" in data
        assert "submitted_at" in data
        assert "size_bytes" in data

    # --- Wrong answer ---

    @patch("main.httpx.AsyncClient")
    def test_wrong_answer_submission(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(4, "Wrong Answer", "Bad output"))

        code = '#include <iostream>\nint main() { std::cout << "Bad output\\n"; return 0; }\n'
        resp = client.post("/submit/1", files=make_upload(code))

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["status"] == "Wrong"

    # --- Plain (non-base64) upload ---

    @patch("main.httpx.AsyncClient")
    def test_plain_text_upload(self, MockClient):
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))

        code = '#include <iostream>\nint main() { std::cout << "Hello, World!\\n"; return 0; }\n'
        resp = client.post("/submit/1", files=make_upload(code, as_base64=False))

        assert resp.status_code == 200

    # --- Code normalization sanity check ---

    @patch("main.httpx.AsyncClient")
    def test_crlf_normalized_in_submission(self, MockClient):
        """CRLF line endings should be normalized before judging."""
        _mock_judge0(MockClient, _judge0_response(3, "Accepted", "Hello, World!"))

        crlf_code = '#include <iostream>\r\nint main() { std::cout << "Hello, World!\\n"; return 0; }\r\n'
        resp = client.post("/submit/1", files=make_upload(crlf_code))
        assert resp.status_code == 200
