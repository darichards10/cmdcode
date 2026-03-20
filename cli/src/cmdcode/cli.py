import base64
import json
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
SERVER_URL = "http://3.88.172.28:8000"  # temp home


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