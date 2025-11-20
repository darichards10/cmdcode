import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from pathlib import Path
import sys
import shutil
import requests

app = typer.Typer(
    name="cmdcode",
    help="cmdcode — terminal coding practice platform",
    add_completion=False
)
console = Console()

SERVER_URL = "http://127.0.0.1:8000"

@app.command()
def get(problem_id: int):
    """Fetch problem from your local cmdcode server"""
    try:
        resp = requests.get(f"{SERVER_URL}/problems/{problem_id}")
        if resp.status_code != 200:
            console.print(f"[red]Problem {problem_id} not found on server[/red]")
            return

        data = resp.json()

        # Create clean folder name: 001-hello-world
        slug = data["title"].lower().replace(" ", "-").replace(",", "").replace("!", "")
        folder_name = f"{problem_id:04d}-{slug}"
        folder = Path(folder_name)

        if folder.exists():
            console.print(f"[yellow]Folder already exists:[/yellow] {folder_name}")
            console.print("   → Opening existing problem")
        else:
            folder.mkdir(exist_ok=True)
            (folder / ".cmdcode").mkdir(exist_ok=True)  # for future metadata

            # Write README
            readme_path = folder / "README.md"
            readme_path.write_text(f"# {data['id']}. {data['title']}\n\n{data['description']}")

            # Write solution file
            solution_path = folder / "solution.cpp"
            solution_path.write_text(data["starter_code"]["cpp"])

            console.print(f"[bold green]Created problem folder:[/bold green] [cyan]./{folder_name}[/]")
            console.print(f"   [green]README.md[/]     → problem statement")
            console.print(f"   [green]solution.cpp[/]  → ready to code")

        # Final beautiful output
        console.print("\n" + "═" * 60)
        console.print(f"[bold magenta]Problem {data['id']}: {data['title']}[/bold magenta]")
        console.print("═" * 60)
        console.print(Markdown(data["description"]))
        console.print("\n[bold cyan]Next steps:[/bold cyan]")
        console.print(f"   cd {folder_name}")
        console.print(f"   nvim solution.cpp")
        console.print(f"   cmdcode submit {problem_id}")

    except requests.ConnectionError:
        console.print("[red]Cannot connect to cmdcode server[/red]")
        console.print("Start it: [bold]cd ~/cmdcode/server && uvicorn main:app --reload[/bold]")

@app.command()
def submit( 
    problem_id: int,
    file: str = typer.Argument("solution.cpp", help="Source file to submit"),
    ):
    """Submit code — creates submission object and logs it"""
    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found:[/red] {file}")
        return

    try:
        with open(file, "rb") as f:
            files = {"file": (file, f, "text/cpp")}
            console.print(f"[bold blue]Submitting[/bold blue] [cyan]{file}[/] → Problem [magenta]{problem_id}[/]")
            with console.status("[bold green]Creating submission object...[/bold green]"):
                resp = requests.post(f"{SERVER_URL}/submit/{problem_id}", files=files, timeout=10)

        if resp.status_code == 200:
            result = resp.json()
            console.print(Panel(
               # f"Problem: {result['problem_id']}\n"
                f"Submission: {result['submission_id']}\n"
                f"File: {result['filename']}\n"
                f"Time: {result['submitted_at']}\n"
                f"Size: {result['size_bytes']} bytes\n"
                f"Passed: {result['passed']}",
                title="Submission Logged",
                border_style="bright_green"
            ))
        else:
            console.print(f"[red]Server error: {resp.status_code}[/red]")

    except requests.ConnectionError:
        console.print("[red]Server not running[/red]")

if __name__ == "__main__":
    app()