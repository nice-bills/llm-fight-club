import re
import os
import time
import json
import random
import sys
from dotenv import load_dotenv
from litellm import completion
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

# Initialize Rich Console
console = Console()

load_dotenv()

def clean_text(text):
    # Remove <think>...</think> blocks and whitespace
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned.strip()

def load_models():
    try:
        if not os.path.exists("models_pool.json"):
            console.print("[yellow]models_pool.json not found. Run scripts/discover_models.py first.[/yellow]")
            return []
        with open("models_pool.json", "r") as f:
            pool = json.load(f)
        
        all_models = []
        for provider in pool:
            # Skip huggingface entirely for now
            if provider == "huggingface": continue
            all_models.extend(pool[provider])
        
        # Unique models only
        all_models = list(set(all_models))
            
        # Filter for top models
        keywords = ["kimi", "qwen", "glm", "minimax", "llama", "gemma", "mistral"]
        filtered_models = [
            m for m in all_models 
            if any(k in m.lower() for k in keywords)
        ]
        
        if not filtered_models:
            return all_models
            
        return filtered_models
    except Exception as e:
        console.print(f"[bold red]Error loading models_pool.json:[/bold red] {e}")
        return []

def get_model_lab(model_id):
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

def generate_random_topic(fallback_model):
    topic_model = "groq/llama-3.3-70b-versatile"
    prompt = "Generate ONE controversial debate topic (technical/ethical/societal). Single question format."
    try:
        resp = completion(model=topic_model, messages=[{"role": "user", "content": prompt}], max_tokens=60, timeout=15)
        return clean_text(resp.choices[0].message.content).replace('"', '')
    except Exception:
        try:
            resp = completion(model=fallback_model, messages=[{"role": "user", "content": prompt}], max_tokens=60, timeout=15)
            return clean_text(resp.choices[0].message.content).replace('"', '')
        except Exception:
            return "Should AI be granted legal personhood?"

def get_single_judge_verdict(judge_model, topic, text_a, text_b):
    # Try JSON format first - it's standard for most smart models now
    judge_prompt = f"""
    Topic: {topic}
    Fighter A: {text_a}
    Fighter B: {text_b}
    
    Rate A and B (0-10) on LOGIC and SUBSTANCE. Ignore tone and aggression.
    Focus purely on who made the better points.
    
    Output valid JSON:
    {{
        "score_a": <int>,
        "score_b": <int>,
        "reason": "<detailed 1-2 sentence explanation>"
    }}
    """
    try:
        response = completion(
            model=judge_model,
            messages=[{"role": "user", "content": judge_prompt}],
            max_tokens=500, # Increased to allow full JSON completion
            timeout=120,    # Increased to 120s for deep thinking
            response_format={"type": "json_object"} if any(p in judge_model for p in ["groq", "mistral", "openai"]) else None
        )
        content = response.choices[0].message.content
        
        try:
            data = json.loads(content)
            return {
                "judge": judge_model,
                "score_a": int(data.get("score_a", 5)),
                "score_b": int(data.get("score_b", 5)),
                "reason": str(data.get("reason", "No reason."))
            }
        except json.JSONDecodeError:
            # Fallback Regex for models that return text despite JSON request
            s_a = re.search(r"score_a.*?(\d+)", content, re.IGNORECASE)
            s_b = re.search(r"score_b.*?(\d+)", content, re.IGNORECASE)
            # Use single quotes for outer string to avoid syntax error with double quotes inside
            reason = re.search(r'reason.*?["\':](.*?)["}]', content, re.IGNORECASE | re.DOTALL)
            
            return {
                "judge": judge_model,
                "score_a": int(s_a.group(1)) if s_a else 5,
                "score_b": int(s_b.group(1)) if s_b else 5,
                "reason": reason.group(1).strip() if reason else "Parse error."
            }
    except Exception as e:
        return {"judge": judge_model, "score_a": 5, "score_b": 5, "reason": f"Timeout/Error: {str(e)[:50]}"}

def get_fighter_response(model, system_prompt, prompt, retries=1):
    for attempt in range(retries + 1):
        try:
            resp = completion(
                model=model, 
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], 
                max_tokens=400, 
                timeout=45
            )
            text = clean_text(resp.choices[0].message.content)
            if text and len(text) > 5: 
                return text
        except Exception:
            time.sleep(1)
            continue
    return "*[Fighter stood silent]*"

def run_fight_loop():
    try:
        while True:
            all_models = load_models()
            if len(all_models) < 5:
                console.print(f"[red]Need at least 5 models (found {len(all_models)}). Add more keys![/red]")
                break

            # Selection
            fighter_a = random.choice(all_models)
            lab_a = get_model_lab(fighter_a)
            remaining_for_b = [m for m in all_models if get_model_lab(m) != lab_a and m != fighter_a]
            if not remaining_for_b: remaining_for_b = [m for m in all_models if m != fighter_a]
            fighter_b = random.choice(remaining_for_b)
            remaining_for_judges = [m for m in all_models if m != fighter_a and m != fighter_b]
            judges = random.sample(remaining_for_judges, 3)

            # Topic
            with console.status(f"[yellow]Generating topic...[/yellow]"):
                topic = clean_text(generate_random_topic(fighter_a))

            console.print(Panel.fit(
                f"[bold cyan]TOPIC:[/bold cyan] {topic}\n\n"
                f"[red]🔴 {fighter_a}[/red] vs [blue]🔵 {fighter_b}[/blue]\n"
                f"[yellow]👨‍⚖️ JUDGES:[/yellow]\n1. {judges[0]}\n2. {judges[1]}\n3. {judges[2]}",
                title="🥊 NEXT FIGHT", border_style="bold magenta"
            ))

            history = []
            sys_prompt = "You are a ruthless debater. Attack logic. No apologies. Max 3 sentences."

            for round_num in range(1, 6): # 5 ROUNDS
                console.print(Rule(f"ROUND {round_num}", style="dim yellow"))
                
                # Fighter A
                p_a = f"Topic: {topic}. Position: FOR. Open." if round_num == 1 else f"Opponent: '{history[-1]['content']}'. Rebut."
                with console.status(f"[red]{fighter_a} typing...[/red]"):
                    t_a = get_fighter_response(fighter_a, sys_prompt, p_a)
                console.print(Panel(Markdown(t_a), title=f"🔴 {fighter_a}", border_style="red"))
                history.append({"role": "user", "content": t_a})

                # Fighter B
                p_b = f"Topic: {topic}. Position: AGAINST. Open." if round_num == 1 else f"Opponent: '{t_a}'. Rebut."
                with console.status(f"[blue]{fighter_b} typing...[/blue]"):
                    t_b = get_fighter_response(fighter_b, sys_prompt, p_b)
                console.print(Panel(Markdown(t_b), title=f"🔵 {fighter_b}", border_style="blue"))
                history.append({"role": "user", "content": t_b})

                # Judging
                console.print("[dim]Judges are deciding...[/dim]")
                countdown(30, "Judges Deliberating") # 30s pause before showing results

                console.print("[bold yellow]👨‍⚖️ VERDICTS:[/bold yellow]")
                for j in judges:
                    with console.status(f"[yellow]{j} judging...[/yellow]"):
                        v = get_single_judge_verdict(j, topic, t_a, t_b)
                    s_a_col = "green" if v['score_a'] > v['score_b'] else "white"
                    s_b_col = "green" if v['score_b'] > v['score_a'] else "white"
                    console.print(f"[dim]{v['judge'].split('/')[-1]}[/dim]: A:[{s_a_col}]{v['score_a']}[/{s_a_col}] B:[{s_b_col}]{v['score_b']}[/{s_b_col}] - {v['reason']}")

                # 2-MINUTE RATE LIMIT BREAK
                if round_num < 5:
                    countdown(120, "Rate Limit Protection (Round Break)")

            console.print(Rule("FIGHT OVER", style="bold red"))
            countdown(120, "Cooldown before next fight")
            
    except KeyboardInterrupt:
        console.print("\n[bold red]🛑 Fight Club Shutdown.[/bold red]")
        sys.exit(0)
