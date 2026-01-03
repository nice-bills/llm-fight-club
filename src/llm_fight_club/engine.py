import re
import os
import time
import json
import random
import sys
from datetime import datetime
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

class JudgeRotation:
    def __init__(self, model_pool):
        self.pool = list(set(model_pool))
        self.rotation_index = 0
        random.shuffle(self.pool)
    
    def get_judges(self, fighters):
        judges = []
        attempts = 0
        while len(judges) < 3 and attempts < len(self.pool) * 2:
            judge = self.pool[self.rotation_index % len(self.pool)]
            if judge not in fighters and judge not in judges:
                judges.append(judge)
            self.rotation_index += 1
            attempts += 1
        
        if len(judges) < 3:
            remaining = [m for m in self.pool if m not in fighters and m not in judges]
            judges.extend(random.sample(remaining, min(3 - len(judges), len(remaining))))
            
        return judges

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
            if provider == "huggingface": continue
            all_models.extend(pool[provider])
        
        all_models = list(set(all_models))
        keywords = ["kimi", "qwen", "glm", "minimax", "llama", "gemma", "mistral"]
        filtered_models = [m for m in all_models if any(k in m.lower() for k in keywords)]
        return filtered_models if filtered_models else all_models
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
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TimeRemainingColumn(), transient=True) as progress:
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
    judge_prompt = f"""
    Topic: {topic}
    Fighter A: {text_a}
    Fighter B: {text_b}
    Rate A and B (0-10) on LOGIC and SUBSTANCE. Ignore tone.
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
            max_tokens=500,
            timeout=120,
            response_format={"type": "json_object"} if any(p in judge_model for p in ["groq", "mistral", "openai"]) else None
        )
        content = response.choices[0].message.content
        try:
            data = json.loads(content)
            return {"judge": judge_model, "score_a": int(data.get("score_a", 5)), "score_b": int(data.get("score_b", 5)), "reason": str(data.get("reason", "No reason."))}
        except json.JSONDecodeError:
            s_a = re.search(r"score_a.*?(\d+)", content, re.IGNORECASE)
            s_b = re.search(r"score_b.*?(\d+)", content, re.IGNORECASE)
            reason = re.search(r'reason.*?["\':](.*?)["}]', content, re.IGNORECASE | re.DOTALL)
            return {"judge": judge_model, "score_a": int(s_a.group(1)) if s_a else 5, "score_b": int(s_b.group(1)) if s_b else 5, "reason": reason.group(1).strip() if reason else "Parse error."}
    except Exception as e:
        return {"judge": judge_model, "score_a": 5, "score_b": 5, "reason": f"Timeout/Error: {str(e)[:50]}"}

def get_fighter_response(model, system_prompt, prompt, retries=1):
    for attempt in range(retries + 1):
        try:
            resp = completion(model=model, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], max_tokens=400, timeout=45)
            text = clean_text(resp.choices[0].message.content)
            if text and len(text) > 5: return text
        except Exception:
            time.sleep(1)
            continue
    return "*[Fighter stood silent]*"

def save_fight_result(fight_data):
    if not os.path.exists("results"): os.makedirs("results")
    filename = f"results/fight_{fight_data['fight_id']}.json"
    with open(filename, "w") as f: json.dump(fight_data, f, indent=2)

def run_fight_loop():
    try:
        all_models = load_models()
        judge_rotator = JudgeRotation(all_models)
        while True:
            if len(all_models) < 5:
                console.print(f"[red]Need at least 5 models. Found {len(all_models)}.[/red]")
                break
            
            # Selection
            fighter_a = random.choice(all_models)
            lab_a = get_model_lab(fighter_a)
            remaining_for_b = [m for m in all_models if get_model_lab(m) != lab_a and m != fighter_a]
            if not remaining_for_b: remaining_for_b = [m for m in all_models if m != fighter_a]
            fighter_b = random.choice(remaining_for_b)
            judges = judge_rotator.get_judges([fighter_a, fighter_b])

            with console.status("[yellow]Generating topic...[/yellow]"):
                topic = clean_text(generate_random_topic(fighter_a))

            fight_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            console.print(Panel.fit(
                f"[bold cyan]TOPIC:[/bold cyan] {topic}\n\n"
                f"[red]🔴 {fighter_a}[/red] vs [blue]🔵 {fighter_b}[/blue]\n"
                f"[yellow]👨‍⚖️ JUDGES:[/yellow]\n1. {judges[0]}\n2. {judges[1]}\n3. {judges[2]}",
                title=f"🥊 FIGHT #{fight_id}", border_style="bold magenta"
            ))

            fight_data = {"fight_id": fight_id, "timestamp": str(datetime.now()), "topic": topic, "red_model": fighter_a, "blue_model": fighter_b, "judges": judges, "rounds": [], "aggregate_scores": {"red": 0, "blue": 0}, "winner": None, "decision_type": None}
            history, total_red_score, total_blue_score = [], 0, 0
            judge_round_wins = {j: {"red": 0, "blue": 0} for j in judges}
            sys_prompt = "You are a ruthless debater. Attack logic. No apologies. Max 3 sentences."

            for round_num in range(1, 6):
                console.print(Rule(f"ROUND {round_num}", style="dim yellow"))
                
                # Turn A
                p_a = f"Topic: {topic}. Position: FOR. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{history[-1]['content']}'. Rebut."
                with console.status(f"[red]{fighter_a} typing...[/red]"): t_a = get_fighter_response(fighter_a, sys_prompt, p_a)
                console.print(Panel(Markdown(t_a), title=f"🔴 {fighter_a}", border_style="red"))
                history.append({"role": "user", "content": t_a, "fighter": "red"})

                # Turn B
                p_b = f"Topic: {topic}. Position: AGAINST. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{t_a}'. Rebut."
                with console.status(f"[blue]{fighter_b} typing...[/blue]"): t_b = get_fighter_response(fighter_b, sys_prompt, p_b)
                console.print(Panel(Markdown(t_b), title=f"🔵 {fighter_b}", border_style="blue"))
                history.append({"role": "user", "content": t_b, "fighter": "blue"})

                console.print("[dim]Judges are deciding...[/dim]")
                countdown(30, "Judges Deliberating")
                
                round_verdicts, red_round_wins, blue_round_wins = [], 0, 0
                console.print("[bold yellow]👨‍⚖️ VERDICTS:[/bold yellow]")
                for idx, j in enumerate(judges):
                    with console.status(f"[yellow]Judge {idx+1} judging...[/yellow]"): v = get_single_judge_verdict(j, topic, t_a, t_b)
                    if v['score_a'] > v['score_b']: red_round_wins += 1
                    elif v['score_b'] > v['score_a']: blue_round_wins += 1
                    total_red_score += v['score_a']
                    total_blue_score += v['score_b']
                    if v['score_a'] > v['score_b']: judge_round_wins[j]["red"] += 1
                    elif v['score_b'] > v['score_a']: judge_round_wins[j]["blue"] += 1
                    
                    s_a_col = "green" if v['score_a'] > v['score_b'] else "white"
                    s_b_col = "green" if v['score_b'] > v['score_a'] else "white"
                    console.print(f"[dim]{j.split('/')[-1]}[/dim]: A:[{s_a_col}]{v['score_a']}[/{s_a_col}] B:[{s_b_col}]{v['score_b']}[/{s_b_col}] - {v['reason']}")
                    round_verdicts.append(v)

                if red_round_wins > blue_round_wins: console.print(f"\n[bold red]🥊 ROUND {round_num} WINNER: RED ({red_round_wins}-{blue_round_wins})[/bold red]")
                elif blue_round_wins > red_round_wins: console.print(f"\n[bold blue]🥊 ROUND {round_num} WINNER: BLUE ({blue_round_wins}-{red_round_wins})[/bold blue]")
                else: console.print(f"\n[bold yellow]🥊 ROUND {round_num} RESULT: DRAW[/bold yellow]")

                fight_data["rounds"].append({"round": round_num, "red_text": t_a, "blue_text": t_b, "verdicts": round_verdicts})
                if round_num < 5: countdown(120, "Intermission - Round Recovery")

            # Final result
            fight_data["aggregate_scores"] = {"red": total_red_score, "blue": total_blue_score}
            judge_winners = []
            for j in judges:
                r_sum = sum(r["verdicts"][judges.index(j)]["score_a"] for r in fight_data["rounds"])
                b_sum = sum(r["verdicts"][judges.index(j)]["score_b"] for r in fight_data["rounds"])
                if r_sum > b_sum: judge_winners.append("red")
                elif b_sum > r_sum: judge_winners.append("blue")
                else: judge_winners.append("draw")

            # Sudden Death check if judge wins are equal (e.g. 1-1-1 or 0-0-3 etc)
            red_wins, blue_wins = judge_winners.count("red"), judge_winners.count("blue")
            if red_wins == blue_wins:
                console.print(Rule("☠️ SUDDEN DEATH ☠️", style="bold red"))
                sd_prompt = "SUDDEN DEATH: Why do you deserve to win this fight? Be ruthless."
                with console.status(f"[red]{fighter_a} SUDDEN DEATH...[/red]"): t_a = get_fighter_response(fighter_a, sys_prompt, sd_prompt)
                console.print(Panel(Markdown(t_a), title=f"🔴 {fighter_a} (SD)", border_style="red"))
                with console.status(f"[blue]{fighter_b} SUDDEN DEATH...[/blue]"): t_b = get_fighter_response(fighter_b, sys_prompt, sd_prompt)
                console.print(Panel(Markdown(t_b), title=f"🔵 {fighter_b} (SD)", border_style="blue"))
                countdown(60, "Final Deliberation")
                sd_red, sd_blue = 0, 0
                for idx, j in enumerate(judges):
                    v = get_single_judge_verdict(j, "SUDDEN DEATH", t_a, t_b)
                    if v['score_a'] >= v['score_b']:
                        if v['score_a'] == v['score_b']: v['score_a'] += 1
                        sd_red += 1
                        winner_col = "red"
                    else: sd_blue += 1
                    winner_col = "blue"
                    console.print(f"Judge {idx+1} SD Vote: [{winner_col}]{winner_col.upper()}[/{winner_col}]")
                winner = "red" if sd_red > sd_blue else "blue"
                decision_type = "Sudden Death Victory"
            else:
                winner = "red" if red_wins > blue_wins else "blue"
                decision_type = "Unanimous Decision" if (red_wins == 3 or blue_wins == 3) else "Split Decision"

            fight_data["winner"], fight_data["decision_type"] = winner, decision_type
            winner_name = fighter_a if winner == "red" else fighter_b
            winner_col = "bold red" if winner == "red" else "bold blue"
            console.print(Rule("FIGHT RESULTS", style="bold magenta"))
            console.print(Panel(f"[bold]Winner:[/bold] [{winner_col}]{winner_name}[/{winner_col}]\n[bold]Decision:[/bold] {decision_type}\n[bold]Total Points:[/bold] Red: {total_red_score} | Blue: {total_blue_score}", title="🏆 VERDICT", border_style="magenta"))
            console.print("[dim]Judges:[/dim] " + ", ".join([j.split('/')[-1] for j in judges]))
            save_fight_result(fight_data)
            countdown(120, "Next fight starting")
    except KeyboardInterrupt:
        console.print("\n[bold red]🛑 Shutdown.[/bold red]")
        sys.exit(0)

if __name__ == "__main__":
    run_fight_loop()