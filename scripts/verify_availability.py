import os
import asyncio
import json
from dotenv import load_dotenv
from litellm import acompletion
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()

async def test_model(model_id):
    """Returns (is_available, model_id, error_msg)"""
    try:
        await acompletion(
            model=model_id,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=1,
            timeout=45
        )
        return True, model_id, ""
    except Exception as e:
        return False, model_id, str(e)

async def main():
    try:
        with open("models_pool.json", "r") as f:
            pool = json.load(f)
    except FileNotFoundError:
        console.print("[red]models_pool.json not found. Run scripts/discover_models.py first.[/red]")
        return
        
    all_potential = []
    for provider in pool:
        all_potential.extend(pool[provider])
    
    console.print(f"[yellow]Verifying access for {len(all_potential)} discovered models...[/yellow]")
    
    tasks = [test_model(m) for m in all_potential]
    results = await asyncio.gather(*tasks)
    
    verified_pool = {
        "groq": [],
        "gemini": [],
        "mistral": [],
        "huggingface": []
    }
    
    table = Table(title="Model Availability Verification")
    table.add_column("Model ID", style="cyan")
    table.add_column("Status", style="bold")

    for success, mid, err in results:
        status = "[green]✅ Active[/green]" if success else "[red]❌ Failed[/red]"
        table.add_row(mid, status)
        
        if success:
            provider = mid.split('/')[0]
            if provider in verified_pool:
                verified_pool[provider].append(mid)

    console.print(table)
    
    # Overwrite the pool with only verified models
    with open("models_pool.json", "w") as f:
        # Remove any empty provider lists
        final_pool = {k: v for k, v in verified_pool.items() if v}
        json.dump(final_pool, f, indent=2)
    
    count = sum(len(v) for v in final_pool.values())
    console.print(f"\n[bold green]Overwrote models_pool.json with {count} VERIFIED models.[/bold green]")

if __name__ == "__main__":
    asyncio.run(main())
