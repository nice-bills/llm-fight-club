import random
import sys
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from llm_fight_club.core.models import load_models, get_model_lab
from llm_fight_club.core.judging import JudgeRotation
from llm_fight_club.core.fight import FightManager
from llm_fight_club.utils.text import clean_text
from llm_fight_club.utils.ui import countdown
from llm_fight_club.core.judging import get_single_judge_verdict # for topic gen fallback if needed

console = Console()

def run_fight_loop():
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
            from litellm import completion
            def generate_topic(fallback_model):
                try:
                    resp = completion(
                        model="groq/llama-3.3-70b-versatile", 
                        messages=[{"role": "user", "content": "Generate ONE controversial debate topic (technical/ethical/societal). Single question format."}],
                        max_tokens=60, 
                        timeout=15
                    )
                    return clean_text(resp.choices[0].message.content).replace('"', '')
                except:
                    return "Should AI be granted legal personhood?"

            with console.status("[yellow]Generating topic...[/yellow]"):
                topic = generate_topic(fighter_a)

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
                t_a, t_b = fight.run_round(round_num)
                fight.score_round(round_num, t_a, t_b, countdown)
                
                if round_num < 5:
                    countdown(120, "Intermission - Round Recovery")

            # 5. Finalize
            red_wins, blue_wins = fight.resolve_winner()
            
            # Sudden Death check
            if red_wins == blue_wins:
                winner_key = fight.run_sudden_death(countdown)
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