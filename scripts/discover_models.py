import os
import requests
import json
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()

def get_groq_models():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return []
    try:
        resp = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code == 200:
            return [f"groq/{m['id']}" for m in resp.json()["data"]]
    except Exception as e:
        console.print(f"[red]Groq Discovery Error:[/red] {e}")
    return []

def get_gemini_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return []
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        resp = requests.get(url)
        if resp.status_code == 200:
            # Filter for generation models only
            return [f"gemini/{m['name'].replace('models/', '')}" for m in resp.json().get('models', []) 
                    if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception as e:
        console.print(f"[red]Gemini Discovery Error:[/red] {e}")
    return []

def search_huggingface_hub(query, limit=5):
    """Searches HF Hub for top models by likes matching the query."""
    api_key = os.getenv("HUGGINGFACE_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    try:
        # Search for text-generation/conversational models, sorted by likes
        params = {
            "search": query,
            "limit": limit,
            "sort": "likes",
            "direction": "-1",
            "filter": "text-generation" # or 'conversational'
        }
        resp = requests.get("https://huggingface.co/api/models", params=params, headers=headers)
        
        if resp.status_code == 200:
            return [f"huggingface/{m['id']}" for m in resp.json()]
    except Exception as e:
        console.print(f"[red]HF Search Error ({query}):[/red] {e}")
    return []

def get_mistral_models():
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key: return []
    try:
        resp = requests.get("https://api.mistral.ai/v1/models", headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code == 200:
            return [f"mistral/{m['id']}" for m in resp.json()["data"]]
    except Exception as e:
        console.print(f"[red]Mistral Discovery Error:[/red] {e}")
    return []

def main():
    table = Table(title="Discovered Models (No Guessing)")
    table.add_column("Source", style="cyan")
    table.add_column("Model ID", style="green")

    discovered = {
        "groq": get_groq_models(),
        "gemini": get_gemini_models(),
        "mistral": get_mistral_models(),
        "huggingface": []
    }

    # Add Groq, Gemini, Mistral to table
    for m in discovered["groq"]: table.add_row("Groq API", m)
    for m in discovered["gemini"]: table.add_row("Gemini API", m)
    for m in discovered["mistral"]: table.add_row("Mistral API", m)

    # Search HF for specific families requested
    hf_families = ["kimi", "qwen", "glm", "minimax"]
    console.print(f"[yellow]Searching Hugging Face Hub for: {', '.join(hf_families)}...[/yellow]")
    
    for family in hf_families:
        found = search_huggingface_hub(family)
        discovered["huggingface"].extend(found)
        for m in found:
            table.add_row(f"HF Search ({family})", m)

    console.print(table)
    
    # Save
    with open("models_pool.json", "w") as f:
        json.dump(discovered, f, indent=2)
    console.print(f"\n[bold green]Saved {sum(len(v) for v in discovered.values())} models to models_pool.json[/bold green]")

if __name__ == "__main__":
    main()
