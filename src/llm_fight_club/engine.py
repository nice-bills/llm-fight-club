import random
import sys
import asyncio
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.markdown import Markdown
from litellm import acompletion # async import

from llm_fight_club.core.models import load_models, get_model_lab
from llm_fight_club.core.judging import JudgeRotation
from llm_fight_club.core.fight import FightManager
from llm_fight_club.utils.text import clean_text
from llm_fight_club.utils.ui import countdown

console = Console()

async def generate_random_topic(fallback_model):
    topic_model = "groq/llama-3.3-70b-versatile"
    
    categories = [
        "Bioethics (e.g. CRISPR, Cloning)",
        "Space Exploration (e.g. Mars Rights, Alien Contact)",
        "Economics (e.g. UBI, Crypto, Corporate Sovereignty)",
        "Transhumanism (e.g. Mind Uploading, Cybernetics)",
        "Environmental Engineering (e.g. Geoengineering, De-extinction)",
        "Digital Rights (e.g. Privacy vs Security, Internet Censorship)"
    ]
    selected_category = random.choice(categories)
    
    prompt = f"""
    Generate ONE controversial debate topic specifically about: {selected_category}.
    
    Rules:
    - It must be a specific, high-stakes ethical or societal dilemma.
    - Format: Single question ending in '?'.
    - DO NOT generate generic "AI takes over world" topics unless relevant to the category.
    
    Example: 'Should corporations be allowed to own genetic patents on extinct species?'
    """
    try:
        # Try dedicated topic generator first
        resp = await acompletion(model=topic_model, messages=[{"role": "user", "content": prompt}], max_tokens=60, timeout=15)
        return clean_text(resp.choices[0].message.content).replace('"', '')
    except Exception:
        try:
            resp = await acompletion(model=fallback_model, messages=[{"role": "user", "content": prompt}], max_tokens=60, timeout=15)
            return clean_text(resp.choices[0].message.content).replace('"', '')
        except Exception:
            return "Should AI be granted legal personhood?"

async def run_fight_loop():
    try:
        all_models = load_models()
        judge_rotator = JudgeRotation(all_models)
        
        while True:
            if len(all_models) < 5:
                console.print(f"[red]Need at least 5 models. Found {len(all_models)}.[/red]")
                break
            
            # 1. Selection
            fighter_a = random.choice(all_models)
            lab_a = get_model_lab(fighter_a)
            remaining_for_b = [m for m in all_models if get_model_lab(m) != lab_a and m != fighter_a]
            if not remaining_for_b: 
                remaining_for_b = [m for m in all_models if m != fighter_a]
            fighter_b = random.choice(remaining_for_b)
            judges = judge_rotator.get_judges([fighter_a, fighter_b])

            # 2. Topic
            with console.status("[yellow]Generating topic...[/yellow]"):
                topic = await generate_random_topic(fighter_a)

            # 3. Initialize Fight
            sys_prompt = "You are a ruthless debater. Attack logic. No apologies. Max 3 sentences."
            fight = FightManager(fighter_a, fighter_b, judges, topic, sys_prompt)

            console.print(Panel.fit(
                f"[bold cyan]TOPIC:[/bold cyan] {topic}\n\n"
                f"[red]🔴 {fighter_a}[/red] vs [blue]🔵 {fighter_b}[/blue]\n"
                f"[yellow] JUDGES:[/yellow]\n1. {judges[0]}\n2. {judges[1]}\n3. {judges[2]}",
                title=f" FIGHT #{fight.fight_id}", 
                border_style="bold magenta"
            ))

            # 4. Main Rounds
            for round_num in range(1, 6):
                # Need to update FightManager.run_round to be async
                # Since we can't change FightManager signature easily without rewriting it in fight.py
                # We will manually call the async helpers here or update fight.py to have async run_round
                
                console.print(Rule(f"ROUND {round_num}", style="dim yellow"))
                
                # Turn A
                p_a = f"Topic: {fight.topic}. Position: FOR. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{fight.history[-1]['content']}'. Rebut."
                with console.status(f"[red]{fight.fighter_a} typing...[/red]"): 
                    t_a = await fight.get_fighter_response(fight.fighter_a, p_a)
                console.print(Panel(Markdown(t_a), title=f"🔴 {fight.fighter_a}", border_style="red"))
                fight.history.append({"role": "user", "content": t_a, "fighter": "red"})

                # Turn B
                p_b = f"Topic: {fight.topic}. Position: AGAINST. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{t_a}'. Rebut."
                with console.status(f"[blue]{fight.fighter_b} typing...[/blue]"): 
                    t_b = await fight.get_fighter_response(fight.fighter_b, p_b)
                console.print(Panel(Markdown(t_b), title=f"🔵 {fight.fighter_b}", border_style="blue"))
                fight.history.append({"role": "user", "content": t_b, "fighter": "blue"})

                # Scoring (Now parallel!)
                console.print("[dim]Judges are deciding...[/dim]")
                
                # We need to expose the scoring logic here to make it async parallel
                from llm_fight_club.core.judging import get_single_judge_verdict
                
                console.print("[bold yellow]VERDICTS:[/bold yellow]")
                
                # Run judges in parallel
                judge_tasks = [get_single_judge_verdict(j, fight.topic, t_a, t_b) for j in fight.judges]
                round_verdicts = []
                red_round_wins = 0
                blue_round_wins = 0
                
                # Spinner while waiting for all
                with console.status("[yellow]Judges deliberating (Async)...[/yellow]"):
                    verdicts = await asyncio.gather(*judge_tasks)
                
                for idx, v in enumerate(verdicts):
                    j_name = fight.judges[idx]
                    
                    if v['score_a'] > v['score_b']: red_round_wins += 1
                    elif v['score_b'] > v['score_a']: blue_round_wins += 1
                    
                    fight.total_red_score += v['score_a']
                    fight.total_blue_score += v['score_b']
                    
                    if v['score_a'] > v['score_b']: fight.judge_round_wins[j_name]["red"] += 1
                    elif v['score_b'] > v['score_a']: fight.judge_round_wins[j_name]["blue"] += 1
                    
                    s_a_col = "green" if v['score_a'] > v['score_b'] else "white"
                    s_b_col = "green" if v['score_b'] > v['score_a'] else "white"
                    
                    console.print(f"[dim]{j_name.split('/')[-1]}[/dim]: A:[{s_a_col}]{v['score_a']}[/{s_a_col}] B:[{s_b_col}]{v['score_b']}[/{s_b_col}] - {v['reason']}")
                    round_verdicts.append(v)

                if red_round_wins > blue_round_wins: 
                    console.print(f"\n[bold red] ROUND {round_num} WINNER: RED ({red_round_wins}-{blue_round_wins})[/bold red]")
                elif blue_round_wins > red_round_wins: 
                    console.print(f"\n[bold blue] ROUND {round_num} WINNER: BLUE ({blue_round_wins}-{red_round_wins})[/bold blue]")
                else: 
                    console.print(f"\n[bold yellow] ROUND {round_num} RESULT: DRAW[/bold yellow]")

                fight.fight_data["rounds"].append({
                    "round": round_num, 
                    "red_text": t_a, 
                    "blue_text": t_b, 
                    "verdicts": round_verdicts
                })
                
                if round_num < 5:
                    countdown(120, "Intermission - Round Recovery")

            # 5. Finalize
            red_wins, blue_wins = fight.resolve_winner()
            
            # Sudden Death check
            if red_wins == blue_wins:
                # fight.run_sudden_death needs to be async too
                # For now, let's implement inline SD
                console.print(Rule("SUDDEN DEATH", style="bold red"))
                sd_prompt = "SUDDEN DEATH: Why do you deserve to win this fight? Be ruthless."
                
                with console.status(f"[red]{fight.fighter_a} SUDDEN DEATH...[/red]"): 
                    t_a = await fight.get_fighter_response(fight.fighter_a, sd_prompt)
                console.print(Panel(Markdown(t_a), title=f"🔴 {fight.fighter_a} (SD)", border_style="red"))
                
                with console.status(f"[blue]{fight.fighter_b} SUDDEN DEATH...[/blue]"): 
                    t_b = await fight.get_fighter_response(fight.fighter_b, sd_prompt)
                console.print(Panel(Markdown(t_b), title=f"🔵 {fight.fighter_b} (SD)", border_style="blue"))
                
                countdown(60, "Final Deliberation")
                
                sd_tasks = [get_single_judge_verdict(j, "SUDDEN DEATH", t_a, t_b) for j in fight.judges]
                with console.status("[yellow]Judges voting...[/yellow]"):
                    sd_verdicts = await asyncio.gather(*sd_tasks)
                
                sd_red, sd_blue = 0, 0
                for idx, v in enumerate(sd_verdicts):
                    if v['score_a'] >= v['score_b']:
                        if v['score_a'] == v['score_b']: v['score_a'] += 1
                        sd_red += 1
                        winner_col = "red"
                    else: 
                        sd_blue += 1
                        winner_col = "blue"
                    console.print(f"Judge {idx+1} SD Vote: [{winner_col}]{winner_col.upper()}[/{winner_col}]")
                
                winner_key = "red" if sd_red > sd_blue else "blue"
                decision_type = "Sudden Death Victory"
            else:
                winner_key = "red" if red_wins > blue_wins else "blue"
                decision_type = "Unanimous Decision" if (red_wins == 3 or blue_wins == 3) else "Split Decision"

            fight.fight_data["winner"] = winner_key
            fight.fight_data["decision_type"] = decision_type
            
            winner_name = fighter_a if winner_key == "red" else fighter_b
            winner_col = "bold red" if winner_key == "red" else "bold blue"
            
            console.print(Rule("FIGHT RESULTS", style="bold magenta"))
            console.print(Panel(
                f"[bold]Winner:[/bold] [{winner_col}]{winner_name}[/{winner_col}]\n"
                f"[bold]Decision:[/bold] {decision_type}\n"
                f"[bold]Total Points:[/bold] Red: {fight.total_red_score} | Blue: {fight.total_blue_score}", 
                title=" VERDICT", 
                border_style="magenta"
            ))
            
            console.print("[dim]Judges:[/dim] " + ", ".join([j.split('/')[-1] for j in judges]))
            
            fight.save_result()
            
            # 6. Break before next fight
            countdown(120, "Next fight starting")
            
    except KeyboardInterrupt:
        console.print("\n[bold red] Shutdown.[/bold red]")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run_fight_loop())