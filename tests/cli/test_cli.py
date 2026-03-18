"""
Tests for the cmdcode CLI.

Uses Typer's CliRunner to invoke commands without a real network or server.
All HTTP calls (via `requests`) are mocked with unittest.mock.
"""
import base64
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner

from cmdcode.cli import app, __version__

runner = CliRunner()


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
    @patch("cmdcode.cli.requests.get")
    def test_get_creates_folder(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())

        result = runner.invoke(app, ["get", "1"])

        assert result.exit_code == 0
        folder = tmp_path / "0001-hello-world"
        assert folder.exists()

    @patch("cmdcode.cli.requests.get")
    def test_get_creates_readme(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())

        runner.invoke(app, ["get", "1"])

        assert (tmp_path / "0001-hello-world" / "README.md").exists()

    @patch("cmdcode.cli.requests.get")
    def test_get_creates_solution_cpp(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())

        runner.invoke(app, ["get", "1"])

        assert (tmp_path / "0001-hello-world" / "solution.cpp").exists()

    @patch("cmdcode.cli.requests.get")
    def test_get_readme_contains_title(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())

        runner.invoke(app, ["get", "1"])

        readme = (tmp_path / "0001-hello-world" / "README.md").read_text()
        assert "Hello World" in readme

    @patch("cmdcode.cli.requests.get")
    def test_get_existing_folder_warns(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())

        runner.invoke(app, ["get", "1"])  # first call creates it
        result = runner.invoke(app, ["get", "1"])  # second call warns

        assert "already exists" in result.output.lower()

    @patch("cmdcode.cli.requests.get")
    def test_get_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")

        result = runner.invoke(app, ["get", "1"])

        assert result.exit_code == 0  # handled gracefully, no exception
        assert "connect" in result.output.lower()

    @patch("cmdcode.cli.requests.get")
    def test_get_http_error_shows_not_found(self, mock_get):
        import requests
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = resp

        result = runner.invoke(app, ["get", "9999"])

        assert "not found" in result.output.lower()

    @patch("cmdcode.cli.requests.get")
    def test_get_folder_name_slugifies_title(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        payload = _problem_payload()
        payload["title"] = "Two Sum"
        mock_get.return_value = _mock_get(payload)

        runner.invoke(app, ["get", "1"])

        assert (tmp_path / "0001-two-sum").exists()

    @patch("cmdcode.cli.requests.get")
    def test_get_prints_next_steps(self, mock_get, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_get.return_value = _mock_get(_problem_payload())

        result = runner.invoke(app, ["get", "1"])

        assert "cd" in result.output
        assert "cmdcode submit" in result.output


# ---------------------------------------------------------------------------
# submit command
# ---------------------------------------------------------------------------

class TestSubmit:
    def test_submit_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["submit", "1", "nonexistent.cpp"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch("cmdcode.cli.requests.post")
    def test_submit_accepted_shows_verdict(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text('#include <iostream>\nint main() { return 0; }\n')

        mock_post.return_value = _mock_get(_submit_payload(passed=True))

        result = runner.invoke(app, ["submit", "1", str(solution)])

        assert result.exit_code == 0
        assert "Accepted" in result.output

    @patch("cmdcode.cli.requests.post")
    def test_submit_wrong_answer_shows_verdict(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("bad code\n")

        mock_post.return_value = _mock_get(_submit_payload(passed=False))

        result = runner.invoke(app, ["submit", "1", str(solution)])

        assert result.exit_code == 0
        assert "Wrong Answer" in result.output

    @patch("cmdcode.cli.requests.post")
    def test_submit_sends_base64(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("hello\n")

        mock_post.return_value = _mock_get(_submit_payload())

        runner.invoke(app, ["submit", "1", str(solution)])

        call_kwargs = mock_post.call_args
        sent_files = call_kwargs[1]["files"] if call_kwargs[1] else call_kwargs[0][1]
        # The file tuple should carry base64 content-type
        file_tuple = sent_files["file"]
        assert "base64" in file_tuple[2]

    @patch("cmdcode.cli.requests.post")
    def test_submit_request_error_exits(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import requests
        solution = tmp_path / "solution.cpp"
        solution.write_text("code\n")

        mock_post.side_effect = requests.exceptions.RequestException("timeout")

        result = runner.invoke(app, ["submit", "1", str(solution)])

        assert result.exit_code != 0

    @patch("cmdcode.cli.requests.post")
    def test_submit_default_filename_is_solution_cpp(self, mock_post, tmp_path, monkeypatch):
        """Default file arg is 'solution.cpp' when not provided."""
        monkeypatch.chdir(tmp_path)
        solution = tmp_path / "solution.cpp"
        solution.write_text("code\n")

        mock_post.return_value = _mock_get(_submit_payload())

        result = runner.invoke(app, ["submit", "1"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

class TestList:
    @patch("cmdcode.cli.requests.get")
    def test_list_shows_table(self, mock_get):
        problems = [_problem_payload(1), {**_problem_payload(2), "title": "Two Sum", "id": 2}]
        mock_get.return_value = _mock_get(problems)

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Hello World" in result.output
        assert "Two Sum" in result.output

    @patch("cmdcode.cli.requests.get")
    def test_list_shows_difficulty(self, mock_get):
        mock_get.return_value = _mock_get([_problem_payload()])

        result = runner.invoke(app, ["list"])

        assert "Easy" in result.output

    @patch("cmdcode.cli.requests.get")
    def test_list_error_handled_gracefully(self, mock_get):
        mock_get.side_effect = Exception("network error")

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0  # CLI handles errors without crashing
        assert "could not" in result.output.lower()
