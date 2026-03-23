from __future__ import annotations

import base64
import json
import os
import typer
from datetime import datetime, timezone
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from pathlib import Path
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

__version__ = "0.1.0"

app = typer.Typer(
    name="cmdcode",
    help="cmdcode — terminal coding practice platform\n"
         "Practice competitive programming locally",
    add_completion=True,
    no_args_is_help=True,
)

console = Console()
SERVER_URL = os.environ.get("CMDCODE_SERVER_URL", "http://18.212.79.122:8000")


def get_cmdcode_dir() -> Path:
    d = Path.home() / ".cmdcode"
    d.mkdir(exist_ok=True)
    return d


def get_auth_token(server_url: str = SERVER_URL) -> str:
    """Return a valid Bearer token, running challenge-response if needed."""
    d = get_cmdcode_dir()
    session_file = d / "session.json"
    config_file = d / "config.json"

    if session_file.exists():
        try:
            session = json.loads(session_file.read_text())
            expires_at = datetime.fromisoformat(session["expires_at"])
            if datetime.now(timezone.utc) < expires_at:
                return session["token"]
        except Exception:
            pass

    if not config_file.exists():
        console.print("[red]Not registered. Run: cmdcode register[/red]")
        raise typer.Exit(1)

    config = json.loads(config_file.read_text())
    username = config["username"]
    private_key_file = d / "id_ed25519"

    if not private_key_file.exists():
        console.print("[red]Private key not found. Run: cmdcode register[/red]")
        raise typer.Exit(1)

    try:
        resp = requests.get(f"{server_url}/auth/challenge/{username}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        console.print(f"[red]Auth failed (challenge):[/red] {e}")
        raise typer.Exit(1)

    challenge_id = data["challenge_id"]
    nonce = data["nonce"]

    private_key = serialization.load_pem_private_key(
        private_key_file.read_bytes(), password=None,
        backend=default_backend()
    )
    signature = private_key.sign(bytes.fromhex(nonce))
    signature_b64 = base64.b64encode(signature).decode()

    try:
        resp = requests.post(
            f"{server_url}/auth/verify",
            json={"username": username, "challenge_id": challenge_id, "signature": signature_b64},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        console.print(f"[red]Auth failed (verify):[/red] {e}")
        raise typer.Exit(1)

    session_file.write_text(json.dumps({
        "token": result["token"],
        "expires_at": result["expires_at"],
    }))
    return result["token"]


@app.command()
def register(
    username: str = typer.Option(None, prompt="Username (alphanumeric, 3-20 chars)"),
    email: str = typer.Option(None, prompt="Email"),
):
    """Register with cmdcode — generates an Ed25519 keypair and stores it in ~/.cmdcode/."""
    d = get_cmdcode_dir()
    key_file = d / "id_ed25519"

    if key_file.exists():
        console.print("[red]Already registered. Key exists at ~/.cmdcode/id_ed25519[/red]")
        console.print("To re-register, delete ~/.cmdcode/ and run again.")
        raise typer.Exit(1)

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    key_file.write_bytes(private_pem)
    key_file.chmod(0o600)
    (d / "id_ed25519.pub").write_bytes(public_pem)
    (d / "config.json").write_text(json.dumps({
        "username": username,
        "email": email,
        "server_url": SERVER_URL,
    }))

    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/register",
            json={"username": username, "email": email, "public_key": public_pem.decode()},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        console.print(f"[red]Registration failed:[/red] {detail or e}")
        raise typer.Exit(1)
    except requests.RequestException as e:
        console.print(f"[red]Could not reach server:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"\n[bold green]Registered![/bold green] Welcome, [cyan]{username}[/cyan]")
    console.print(f"   Keys saved to [dim]~/.cmdcode/[/dim]")
    console.print(f"   [dim]~/.cmdcode/id_ed25519[/dim]     private key")
    console.print(f"   [dim]~/.cmdcode/id_ed25519.pub[/dim] public key")
    console.print()
    console.print(Panel(
        "[bold yellow]Back up your account now![/bold yellow]\n\n"
        "If you ever lose [dim]~/.cmdcode/id_ed25519[/dim] you will be locked out.\n"
        "Generate recovery codes and store them somewhere safe:\n\n"
        "  [bold cyan]cmdcode recovery-codes[/bold cyan]",
        title="[bold yellow]⚠  Next Step: Save Recovery Codes[/bold yellow]",
        border_style="yellow",
        padding=(1, 2),
    ))


@app.command()
def whoami():
    """Show your registered username and key info."""
    d = get_cmdcode_dir()
    config_file = d / "config.json"
    if not config_file.exists():
        console.print("[yellow]Not registered. Run: cmdcode register[/yellow]")
        raise typer.Exit(1)
    config = json.loads(config_file.read_text())
    console.print(f"[bold cyan]Username:[/bold cyan] {config['username']}")
    console.print(f"[bold cyan]Email:[/bold cyan]    {config['email']}")
    console.print(f"[bold cyan]Keys:[/bold cyan]     ~/.cmdcode/id_ed25519")


@app.command()
def get(problem_id: int):
    """Download a problem and create a ready-to-code folder."""
    try:
        token = get_auth_token()
        resp = requests.get(
            f"{SERVER_URL}/problems/{problem_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in data["title"].lower())
        folder_name = f"{problem_id:04d}-{slug}"
        folder = Path(folder_name)

        if folder.exists():
            console.print(f"[yellow]Folder already exists:[/yellow] [cyan]./{folder_name}[/]")
        else:
            folder.mkdir(exist_ok=True)
            (folder / ".cmdcode").mkdir(exist_ok=True)

            (folder / "README.md").write_text(f"# {data['id']}. {data['title']}\n\n{data['description']}")
            (folder / "solution.cpp").write_text(data["starter_code"]["cpp"])

            console.print(f"[bold green]Created:[/bold green] [cyan]./{folder_name}[/]")
            console.print("   [green]README.md[/]     → problem statement")
            console.print("   [green]solution.cpp[/]  → ready to code")

        console.print("\n" + "═" * 70)
        console.print(f"[bold magenta]Problem {data['id']}: {data['title']}[/bold magenta]")
        console.print("═" * 70)
        console.print(Markdown(data["description"]))
        console.print("\n[bold cyan]Next steps:[/bold cyan]")
        console.print(f"   cd {folder_name}")
        console.print("   nvim solution.cpp")
        console.print(f"   cmdcode submit {problem_id}")

    except requests.ConnectionError:
        console.print("[red]Cannot connect to server[/red]")
        console.print("Start it: [bold]cd ~/cmdcode/server && uvicorn main:app --reload[/bold]")
    except requests.HTTPError as e:
        console.print(f"[red]Problem {problem_id} not found[/red]")


SUPPORTED_EXTENSIONS = {".cpp", ".c", ".py", ".java", ".js", ".ts", ".go", ".rs"}


def _find_solution_file() -> Path | None:
    """Auto-detect a solution file in the current directory."""
    for ext in SUPPORTED_EXTENSIONS:
        candidate = Path(f"solution{ext}")
        if candidate.exists():
            return candidate
    return None


@app.command()
def submit(
    problem_id: int,
    file: str = typer.Argument(None, help="Source file to submit (auto-detected if omitted)"),
):
    """Submit your solution and get instant verdict."""
    if file is None:
        detected = _find_solution_file()
        if detected is None:
            console.print("[red]No solution file found.[/red] Provide a filename or create a solution.* file.")
            raise typer.Exit(1)
        path = detected
    else:
        path = Path(file)

    if not path.exists():
        console.print(f"[red]File not found:[/red] [bold]{file}[/]")
        raise typer.Exit(1)

    raw_bytes = path.read_bytes()
    encoded = base64.b64encode(raw_bytes).decode("utf-8")

    files = {
        "file": (path.name, encoded, "text/plain;base64")
    }

    console.print(f"[bold blue]Submitting[/bold blue] [cyan]{path.name}[/] → Problem [magenta]#{problem_id}[/]")
    
    token = get_auth_token()
    with console.status("[bold green]Waiting for judge...[/bold green]"):
        try:
            resp = requests.post(
                f"{SERVER_URL}/submit/{problem_id}",
                files=files,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to submit:[/red] {e}")
            raise typer.Exit(1)

    # Beautiful result panel
    verdict = "Accepted" if result.get("passed") else "Wrong Answer"
    color = "bright_green" if result.get("passed") else "red"
    
    table = Table(title=f"Submission #{result.get('submission_id', '?')}", border_style=color)
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Problem", f"#{result['problem_id']}")
    table.add_row("File", result['filename'])
    table.add_row("Language", result.get('language', 'cpp'))
    table.add_row("Verdict", f"[{color}]{verdict}[/]")
    table.add_row("Time", result['results'][0].get('time', 'N/A') if result.get('results') else "N/A")
    table.add_row("Memory", str(result['results'][0].get('memory', 'N/A')) if result.get('results') else "N/A")
    table.add_row("Submitted", result['submitted_at'])

    console.print(table)
    console.print(f"\n[bold {color}]{verdict}![/bold {color}] Keep grinding!")


@app.command()
def list():
    """List all available problems on the server."""
    try:
        token = get_auth_token()
        resp = requests.get(
            f"{SERVER_URL}/problems",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        problems = resp.json()

        table = Table(title="Available Problems", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim")
        table.add_column("Title")
        table.add_column("Difficulty", justify="right")

        for p in problems:
            diff = p.get("difficulty", "Medium")
            color = {"Easy": "green", "Medium": "yellow", "Hard": "red"}.get(diff, "white")
            table.add_row(str(p["id"]), p["title"], f"[{color}]{diff}[/]")

        console.print(table)
    except:
        console.print("[red]Could not fetch problems list[/red]")


@app.command()
def stats():
    """Show your submission statistics."""
    d = get_cmdcode_dir()
    config_file = d / "config.json"
    if not config_file.exists():
        console.print("[yellow]Not registered. Run: cmdcode register[/yellow]")
        raise typer.Exit(1)
    config = json.loads(config_file.read_text())
    username = config["username"]

    try:
        token = get_auth_token()
        resp = requests.get(
            f"{SERVER_URL}/users/{username}/stats",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        console.print(f"[red]Could not fetch stats:[/red] {e}")
        raise typer.Exit(1)

    table = Table(title=f"Stats — {username}", border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Problems Solved", str(data["unique_problems_solved"]))
    table.add_row("Total Submissions", str(data["total_submissions"]))
    table.add_row("Accepted", str(data["accepted_submissions"]))
    table.add_row("Accuracy", f"{data['accuracy_rate']}%")
    table.add_row("Favorite Language", data.get("favorite_language") or "—")
    table.add_row("Leaderboard Rank", f"#{data['rank']}" if data.get("rank") else "—")

    console.print(table)


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent submissions to show (max 100)"),
):
    """Show your recent submission history."""
    d = get_cmdcode_dir()
    config_file = d / "config.json"
    if not config_file.exists():
        console.print("[yellow]Not registered. Run: cmdcode register[/yellow]")
        raise typer.Exit(1)
    config = json.loads(config_file.read_text())
    username = config["username"]

    try:
        token = get_auth_token()
        resp = requests.get(
            f"{SERVER_URL}/users/{username}/history",
            params={"limit": limit},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        submissions = resp.json()
    except requests.RequestException as e:
        console.print(f"[red]Could not fetch history:[/red] {e}")
        raise typer.Exit(1)

    if not submissions:
        console.print("[yellow]No submissions yet. Try: cmdcode submit <PROBLEM_ID>[/yellow]")
        return

    table = Table(title=f"Submission History — {username}", border_style="blue")
    table.add_column("ID", style="dim")
    table.add_column("Problem")
    table.add_column("Language")
    table.add_column("Verdict")
    table.add_column("Submitted", style="dim")

    for s in submissions:
        verdict = s["verdict"]
        color = "bright_green" if verdict == "Accepted" else "red"
        table.add_row(
            str(s["submission_id"]),
            f"#{s['problem_id']} {s['problem_title']}",
            s["language"],
            f"[{color}]{verdict}[/]",
            s["submitted_at"],
        )

    console.print(table)


@app.command(name="recovery-codes")
def recovery_codes():
    """Generate a new set of one-time recovery codes for your account."""
    token = get_auth_token()
    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/recovery-codes",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        console.print(f"[red]Failed to generate recovery codes:[/red] {detail or e}")
        raise typer.Exit(1)
    except requests.RequestException as e:
        console.print(f"[red]Could not reach server:[/red] {e}")
        raise typer.Exit(1)

    codes = data["codes"]

    # ── Safety warning panel ────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold yellow]IMPORTANT — READ BEFORE CONTINUING[/bold yellow]\n\n"
        "These codes let you reset your login key if you ever lose it.\n"
        "[bold red]Each code can only be used once.[/bold red] "
        "Generating new codes invalidates all previous ones.\n\n"
        "[bold white]WHERE TO STORE THEM (pick at least one):[/bold white]\n"
        "  [green]✓[/green]  Password manager (1Password, Bitwarden, KeePass, etc.)\n"
        "  [green]✓[/green]  Printed on paper, kept in a safe or drawer\n"
        "  [green]✓[/green]  Encrypted USB drive or external storage\n"
        "  [green]✓[/green]  Secure cloud notes (Notion, encrypted Apple Notes, etc.)\n\n"
        "[bold red]✗  Do NOT save them inside ~/.cmdcode/[/bold red]\n"
        "   That folder holds your key — if it is lost, so are codes stored there.\n\n"
        "[bold red]✗  Do NOT screenshot them on an untrusted device[/bold red]",
        title="[bold red]⚠  RECOVERY CODES — SAVE THESE NOW[/bold red]",
        border_style="red",
        padding=(1, 2),
    ))

    # ── Display the codes ────────────────────────────────────────────────────
    console.print()
    console.print("[bold white]Your recovery codes:[/bold white]")
    console.print()
    for i, code in enumerate(codes, 1):
        console.print(f"  [bold cyan]{i:>2}.[/bold cyan]  [bold yellow]{code}[/bold yellow]")
    console.print()
    console.print("[dim]These codes will NOT be shown again.[/dim]")
    console.print()

    # ── Offer to save to file ────────────────────────────────────────────────
    save = typer.confirm("Save codes to a file now?", default=True)
    if save:
        default_path = Path.home() / "cmdcode-recovery-codes.txt"
        raw = typer.prompt("Save to", default=str(default_path))
        out = Path(raw).expanduser()
        d = get_cmdcode_dir()
        config = {}
        cfg = d / "config.json"
        if cfg.exists():
            config = json.loads(cfg.read_text())
        username = config.get("username", "unknown")
        lines = [
            "cmdcode recovery codes",
            f"Username: {username}",
            f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "IMPORTANT:",
            "  - Each code can only be used once.",
            "  - Keep this file outside ~/.cmdcode/ — that folder may be lost with your key.",
            "  - Store in a password manager or other secure location.",
            "",
        ] + [f"  {code}" for code in codes] + [
            "",
            "To recover your account: cmdcode recover",
        ]
        out.write_text("\n".join(lines) + "\n")
        out.chmod(0o600)
        console.print(f"\n[green]Saved to[/green] [cyan]{out}[/cyan]")
        console.print("[yellow]Move this file to a safe location that is NOT inside ~/.cmdcode/[/yellow]")


@app.command()
def recover():
    """Recover your account using a backup recovery code and a new keypair."""
    console.print()
    console.print(Panel(
        "This will generate a new key pair for your account.\n"
        "Your [bold]username and email are preserved[/bold] — only the key changes.\n\n"
        "You will need one of the recovery codes you saved when you ran\n"
        "[bold cyan]cmdcode recovery-codes[/bold cyan].",
        title="[bold cyan]Account Recovery[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    username = typer.prompt("Username")
    recovery_code = typer.prompt("Recovery code (format: XXXXXX-XXXXXX-XXXXXX)")

    # Generate a brand-new Ed25519 keypair
    console.print("\n[dim]Generating new keypair...[/dim]")
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/recover",
            json={
                "username": username,
                "recovery_code": recovery_code.strip().upper(),
                "new_public_key": public_pem.decode(),
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        console.print(f"\n[red]Recovery failed:[/red] {detail or e}")
        raise typer.Exit(1)
    except requests.RequestException as e:
        console.print(f"\n[red]Could not reach server:[/red] {e}")
        raise typer.Exit(1)

    # Persist the new keypair and config
    d = get_cmdcode_dir()
    key_file = d / "id_ed25519"
    key_file.write_bytes(private_pem)
    key_file.chmod(0o600)
    (d / "id_ed25519.pub").write_bytes(public_pem)
    (d / "config.json").write_text(json.dumps({
        "username": result["username"],
        "email": result["email"],
        "server_url": SERVER_URL,
    }))
    # Clear any stale session token
    session_file = d / "session.json"
    if session_file.exists():
        session_file.unlink()

    console.print()
    console.print(Panel(
        f"[bold green]Recovery successful![/bold green]\n\n"
        f"[bold white]Username:[/bold white] [cyan]{result['username']}[/cyan]\n"
        f"[bold white]Email:[/bold white]    {result['email']}\n\n"
        "Your new key has been saved to [dim]~/.cmdcode/id_ed25519[/dim]\n\n"
        "[yellow]Remember to generate a new set of recovery codes now\n"
        "so you have backups for this new key:[/yellow]\n"
        "  [bold cyan]cmdcode recovery-codes[/bold cyan]",
        title="[bold green]✓ Recovery Complete[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))


@app.command()
def version():
    """Show cmdcode version."""
    console.print(f"[bold cyan]cmdcode[/] version [green]v{__version__}[/]")

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", "-v", is_eager=True)):
    if version:
        console.print(f"[bold cyan]cmdcode[/] v{__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


if __name__ == "__main__":
    app()