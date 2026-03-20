"""
Tests for the cmdcode CLI.

Uses Typer's CliRunner to invoke commands without a real network or server.
All HTTP calls (via `requests`) are mocked with unittest.mock.
get_auth_token is patched for all tests of protected commands so they don't
require a real server or local keypair.
"""
import base64
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from cmdcode.cli import app, __version__

runner = CliRunner()
FAKE_TOKEN = "test-token-abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _problem_payload(problem_id: int = 1):
    return {
        "id": problem_id,
        "title": "Hello World",
        "description": "Print 'Hello, World!'",
        "difficulty": "Easy",
        "starter_code": {
            "cpp": '#include <iostream>\nint main() { return 0; }\n',
        },
        "test_cases": [{"input": "", "output": "Hello, World!\n", "hidden": False}],
    }


def _submit_payload(passed: bool = True):
    return {
        "submission_id": 42,
        "problem_id": 1,
        "filename": "solution.cpp",
        "language": ".cpp",
        "passed": passed,
        "submitted_at": "2024-01-01 00:00:00Z",
        "results": [{"time": "0.001", "memory": 1024}],
    }


def _mock_get(json_data, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception("HTTP Error")
    )
    return resp


def _make_keypair():
    """Return (private_key_pem_bytes, public_key_pem_bytes)."""
    private_key = Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_command(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_shows_cmdcode_label(self):
        result = runner.invoke(app, ["version"])
        assert "cmdcode" in result.output.lower()


# ---------------------------------------------------------------------------
# get command
# ---------------------------------------------------------------------------

class TestGet:
    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_creates_folder(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0
        assert (tmp_path / "0001-hello-world").exists()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_creates_readme(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        runner.invoke(app, ["get", "1"])
        assert (tmp_path / "0001-hello-world" / "README.md").exists()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_creates_solution_cpp(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        runner.invoke(app, ["get", "1"])
        assert (tmp_path / "0001-hello-world" / "solution.cpp").exists()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_readme_contains_title(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        runner.invoke(app, ["get", "1"])
        readme = (tmp_path / "0001-hello-world" / "README.md").read_text()
        assert "Hello World" in readme

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_existing_folder_warns(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        runner.invoke(app, ["get", "1"])
        result = runner.invoke(app, ["get", "1"])
        assert "already exists" in result.output.lower()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_connection_error(self, mock_get, mock_auth):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")
        result = runner.invoke(app, ["get", "1"])
        assert result.exit_code == 0
        assert "connect" in result.output.lower()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_http_error_shows_not_found(self, mock_get, mock_auth):
        import requests
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = resp
        result = runner.invoke(app, ["get", "9999"])
        assert "not found" in result.output.lower()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_folder_name_slugifies_title(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        payload = _problem_payload()
        payload["title"] = "Two Sum"
        mock_get.return_value = _mock_get(payload)
        runner.invoke(app, ["get", "1"])
        assert (tmp_path / "0001-two-sum").exists()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_prints_next_steps(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        result = runner.invoke(app, ["get", "1"])
        assert "cd" in result.output
        assert "cmdcode submit" in result.output

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_get_passes_auth_header(self, mock_get, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())
        runner.invoke(app, ["get", "1"])
        call_kwargs = mock_get.call_args
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("Authorization") == f"Bearer {FAKE_TOKEN}"


# ---------------------------------------------------------------------------
# submit command
# ---------------------------------------------------------------------------

class TestSubmit:
    def test_submit_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["submit", "1", "nonexistent.cpp"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_accepted_shows_verdict(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text('#include <iostream>\nint main() { return 0; }\n')
        mock_post.return_value = _mock_get(_submit_payload(passed=True))
        result = runner.invoke(app, ["submit", "1", str(solution)])
        assert result.exit_code == 0
        assert "Accepted" in result.output

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_wrong_answer_shows_verdict(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("bad code\n")
        mock_post.return_value = _mock_get(_submit_payload(passed=False))
        result = runner.invoke(app, ["submit", "1", str(solution)])
        assert result.exit_code == 0
        assert "Wrong Answer" in result.output

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_sends_base64(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("hello\n")
        mock_post.return_value = _mock_get(_submit_payload())
        runner.invoke(app, ["submit", "1", str(solution)])
        call_kwargs = mock_post.call_args
        sent_files = call_kwargs[1]["files"] if call_kwargs[1] else call_kwargs[0][1]
        file_tuple = sent_files["file"]
        assert "base64" in file_tuple[2]

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_request_error_exits(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import requests
        solution = tmp_path / "solution.cpp"
        solution.write_text("code\n")
        mock_post.side_effect = requests.exceptions.RequestException("timeout")
        result = runner.invoke(app, ["submit", "1", str(solution)])
        assert result.exit_code != 0

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_auto_detects_solution_cpp(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("code\n")
        mock_post.return_value = _mock_get(_submit_payload())
        result = runner.invoke(app, ["submit", "1"])
        assert result.exit_code == 0

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_auto_detects_solution_py(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.py"
        solution.write_text("print('hello')\n")
        mock_post.return_value = _mock_get(_submit_payload())
        result = runner.invoke(app, ["submit", "1"])
        assert result.exit_code == 0
    def test_submit_no_solution_file_errors(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["submit", "1"])
        assert result.exit_code != 0
        assert "no solution file found" in result.output.lower()
        
    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_auto_detects_solution_py(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.py"
        solution.write_text("print('hello')\n")
        mock_post.return_value = _mock_get(_submit_payload())
        result = runner.invoke(app, ["submit", "1"])
        assert result.exit_code == 0

    def test_submit_no_solution_file_errors(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["submit", "1"])
        assert result.exit_code != 0
        assert "no solution file found" in result.output.lower()

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.post")
    def test_submit_passes_auth_header(self, mock_post, mock_auth, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("code\n")
        mock_post.return_value = _mock_get(_submit_payload())
        runner.invoke(app, ["submit", "1", str(solution)])
        call_kwargs = mock_post.call_args
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("Authorization") == f"Bearer {FAKE_TOKEN}"


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

class TestList:
    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_list_shows_table(self, mock_get, mock_auth):
        problems = [_problem_payload(1), {**_problem_payload(2), "title": "Two Sum", "id": 2}]
        mock_get.return_value = _mock_get(problems)
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "Hello World" in result.output
        assert "Two Sum" in result.output

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_list_shows_difficulty(self, mock_get, mock_auth):
        mock_get.return_value = _mock_get([_problem_payload()])
        result = runner.invoke(app, ["list"])
        assert "Easy" in result.output

    @patch("cmdcode.cli.get_auth_token", return_value=FAKE_TOKEN)
    @patch("cmdcode.cli.requests.get")
    def test_list_error_handled_gracefully(self, mock_get, mock_auth):
        mock_get.side_effect = Exception("network error")
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "could not" in result.output.lower()


# ---------------------------------------------------------------------------
# register command
# ---------------------------------------------------------------------------

class TestRegister:
    @patch("cmdcode.cli.requests.post")
    def test_register_creates_keypair(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        mock_post.return_value = _mock_get({"message": "registered", "username": "alice"}, 201)
        result = runner.invoke(app, ["register", "--username", "alice", "--email", "alice@example.com"])
        assert result.exit_code == 0
        assert (tmp_path / ".cmdcode" / "id_ed25519").exists()
        assert (tmp_path / ".cmdcode" / "id_ed25519.pub").exists()

    @patch("cmdcode.cli.requests.post")
    def test_register_saves_config(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        mock_post.return_value = _mock_get({"message": "registered", "username": "bob"}, 201)
        runner.invoke(app, ["register", "--username", "bob", "--email", "bob@example.com"])
        config = json.loads((tmp_path / ".cmdcode" / "config.json").read_text())
        assert config["username"] == "bob"
        assert config["email"] == "bob@example.com"

    @patch("cmdcode.cli.requests.post")
    def test_register_calls_server(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        mock_post.return_value = _mock_get({"message": "registered", "username": "charlie"}, 201)
        runner.invoke(app, ["register", "--username", "charlie", "--email", "charlie@example.com"])
        assert mock_post.called
        call_json = mock_post.call_args[1]["json"]
        assert call_json["username"] == "charlie"
        assert "public_key" in call_json

    def test_register_error_if_key_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        d = tmp_path / ".cmdcode"
        d.mkdir()
        (d / "id_ed25519").write_bytes(b"fake-key")
        result = runner.invoke(app, ["register", "--username", "dave", "--email", "dave@example.com"])
        assert result.exit_code != 0
        assert "already registered" in result.output.lower()

    @patch("cmdcode.cli.requests.post")
    def test_register_server_error_exits(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import requests
        mock_post.side_effect = requests.HTTPError(
            response=MagicMock(json=lambda: {"detail": "Username already taken"})
        )
        result = runner.invoke(app, ["register", "--username", "eve", "--email", "e@example.com"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# whoami command
# ---------------------------------------------------------------------------

class TestWhoami:
    def test_whoami_shows_username(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        d = tmp_path / ".cmdcode"
        d.mkdir()
        (d / "config.json").write_text(json.dumps({
            "username": "frank",
            "email": "frank@example.com",
            "server_url": "http://localhost:8000",
        }))
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 0
        assert "frank" in result.output

    def test_whoami_not_registered_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# get_auth_token helper
# ---------------------------------------------------------------------------

class TestGetAuthToken:
    def test_returns_cached_token(self, tmp_path, monkeypatch):
        """Returns a valid cached token without hitting the server."""
        from datetime import datetime, timedelta, timezone
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        d = tmp_path / ".cmdcode"
        d.mkdir()
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        (d / "session.json").write_text(json.dumps({"token": "cached-tok", "expires_at": expires}))
        (d / "config.json").write_text(json.dumps({"username": "x", "email": "x@x.com", "server_url": "http://localhost"}))

        from cmdcode.cli import get_auth_token
        token = get_auth_token("http://localhost")
        assert token == "cached-tok"

    @patch("cmdcode.cli.requests.get")
    @patch("cmdcode.cli.requests.post")
    def test_performs_challenge_response_when_no_cache(self, mock_post, mock_get, tmp_path, monkeypatch):
        """With no cached token, runs challenge-response and caches the result."""
        from datetime import datetime, timedelta, timezone
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        d = tmp_path / ".cmdcode"
        d.mkdir()
        priv_pem, _ = _make_keypair()
        (d / "id_ed25519").write_bytes(priv_pem)
        (d / "id_ed25519").chmod(0o600)
        (d / "config.json").write_text(json.dumps({"username": "user1", "email": "u@u.com", "server_url": "http://localhost"}))

        # Challenge response mock
        import secrets as sec
        nonce = sec.token_bytes(32).hex()
        mock_get.return_value = _mock_get({"challenge_id": "cid-1", "nonce": nonce})

        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        mock_post.return_value = _mock_get({"token": "new-token", "expires_at": expires})

        from cmdcode.cli import get_auth_token
        token = get_auth_token("http://localhost")
        assert token == "new-token"
        # Should have cached it
        cached = json.loads((d / "session.json").read_text())
        assert cached["token"] == "new-token"

    def test_exits_if_not_registered(self, tmp_path, monkeypatch):
        """Exits with an error if config.json doesn't exist."""
        import click
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from cmdcode.cli import get_auth_token
        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_auth_token("http://localhost")
