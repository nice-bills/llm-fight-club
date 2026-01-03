import os
import json
from rich.console import Console

console = Console()

def load_models():
    """Load and filter models from models_pool.json."""
    try:
        # Assuming the script runs from project root
        pool_path = "models_pool.json"
        if not os.path.exists(pool_path):
            console.print(f"[yellow]{pool_path} not found. Run scripts/discover_models.py first.[/yellow]")
            return []
            
        with open(pool_path, "r") as f:
            pool = json.load(f)
        
        all_models = []
        for provider in pool:
            # ONLY Groq and Mistral for maximum stability/quality
            if provider not in ["groq", "mistral"]:
                continue
            all_models.extend(pool[provider])
        
        # Unique models only
        all_models = list(set(all_models))
            
        # Filter for top models
        keywords = ["kimi", "qwen", "glm", "minimax", "llama", "gemma", "mistral"]
        filtered_models = [
            m for m in all_models 
            if any(k in m.lower() for k in keywords)
        ]
        
        final_models = filtered_models if filtered_models else all_models
        
        # Log Distribution
        dist = {}
        for m in final_models:
            p = m.split('/')[0]
            dist[p] = dist.get(p, 0) + 1
        console.print(f"[dim]Model Pool: {dist}[/dim]")
        
        return final_models
    except Exception as e:
        console.print(f"[bold red]Error loading models_pool.json:[/bold red] {e}")
        return []

def get_model_lab(model_id):
    """Determine the lab/family of a model for matchup logic."""
    mid = model_id.lower()
    if "qwen" in mid: return "qwen"
    if "kimi" in mid or "moonshot" in mid: return "kimi"
    if "glm" in mid or "zai-org" in mid: return "glm"
    if "minimax" in mid: return "minimax"
    if "llama" in mid: return "llama"
    if "gemini" in mid: return "gemini"
    if "openai" in mid or "gpt" in mid: return "openai"
    if "deepseek" in mid: return "deepseek"
    if "mistral" in mid: return "mistral"
    return "other"
