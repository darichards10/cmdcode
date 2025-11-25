import base64
import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from pathlib import Path
import requests

__version__ = "0.1.0"

app = typer.Typer(
    name="cmdcode",
    help="cmdcode — terminal coding practice platform\n"
         "Practice competitive programming locally",
    add_completion=True,
    no_args_is_help=True,
)

console = Console()
SERVER_URL = "http://98.81.154.236:8000"  # temp home


@app.command()
def get(problem_id: int):
    """Download a problem and create a ready-to-code folder."""
    try:
        resp = requests.get(f"{SERVER_URL}/problems/{problem_id}", timeout=10)
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


@app.command()
def submit(
    problem_id: int,
    file: str = typer.Argument("solution.cpp", help="Source file to submit"),
):
    """Submit your solution and get instant verdict."""
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
    
    with console.status("[bold green]Waiting for judge...[/bold green]"):
        try:
            resp = requests.post(f"{SERVER_URL}/submit/{problem_id}", files=files, timeout=30)
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
    table.add_row("Memory", result['results'][0].get('memory', 'N/A') if result.get('results') else "N/A")
    table.add_row("Submitted", result['submitted_at'])

    console.print(table)
    console.print(f"\n[bold {color}]{verdict}![/bold {color}] Keep grinding!")


@app.command()
def list():
    """List all available problems on the server."""
    try:
        resp = requests.get(f"{SERVER_URL}/problems")
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

@app.callback()
def main(version: bool = typer.Option(False, "--version", "-v")):
    if version:
        console.print(f"[bold cyan]cmdcode[/] v{__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()