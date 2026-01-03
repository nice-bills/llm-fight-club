import time
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

def countdown(seconds, message="Waiting"):
    """Visual countdown timer"""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeRemainingColumn(),
        transient=True
    ) as progress:
        task = progress.add_task(f"[cyan]{message}...", total=seconds)
        while not progress.finished:
            progress.update(task, advance=1)
            time.sleep(1)
