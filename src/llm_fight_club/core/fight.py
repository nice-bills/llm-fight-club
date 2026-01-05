import os
import json
import random
import asyncio
import time
from datetime import datetime
from litellm import acompletion
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.rule import Rule

from llm_fight_club.utils.text import clean_text
from llm_fight_club.core.models import get_model_lab
from llm_fight_club.core.judging import get_single_judge_verdict

console = Console()

class FightManager:
    def __init__(self, fighter_a, fighter_b, judges, topic, sys_prompt):
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.judges = judges
        self.topic = topic
        self.sys_prompt = sys_prompt
        self.fight_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.history = []
        self.fight_data = {
            "fight_id": self.fight_id,
            "timestamp": str(datetime.now()),
            "topic": self.topic,
            "red_model": self.fighter_a,
            "blue_model": self.fighter_b,
            "judges": self.judges,
            "rounds": [],
            "aggregate_scores": {"red": 0, "blue": 0},
            "winner": None,
            "decision_type": None
        }
        self.total_red_score = 0
        self.total_blue_score = 0
        self.judge_round_wins = {j: {"red": 0, "blue": 0} for j in self.judges}

    async def get_fighter_response(self, model, prompt, retries=1):
        """Internal helper for fighter calls."""
        
        # Prepare params
        kwargs = {
            "messages": [{"role": "system", "content": self.sys_prompt}, {"role": "user", "content": prompt}],
            "max_tokens": 400,
            "timeout": 45
        }
        
        if "minimax" in model.lower():
            kwargs["model"] = "openai/" + model.split("/")[-1]
            kwargs["api_base"] = "https://api.minimax.io/v1"
            kwargs["api_key"] = os.getenv("MINIMAX_API_KEY")
            kwargs["temperature"] = 1.0
        else:
            kwargs["model"] = model

        for attempt in range(retries + 1):
            try:
                resp = await acompletion(**kwargs)
                text = clean_text(resp.choices[0].message.content)
                if text and len(text) > 5: 
                    return text
            except Exception:
                await asyncio.sleep(1)
                continue
        return "*[Fighter stood silent]*"

    def save_result(self):
        """Save the fight data to results folder."""
        if not os.path.exists("results"):
            os.makedirs("results")
        filename = f"results/fight_{self.fight_id}.json"
        with open(filename, "w") as f:
            json.dump(self.fight_data, f, indent=2)

    def run_round(self, round_num):
        """Executes a single round of the fight."""
        console.print(Rule(f"ROUND {round_num}", style="dim yellow"))
        
        # Turn A
        p_a = f"Topic: {self.topic}. Position: FOR. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{self.history[-1]['content']}'. Rebut."
        with console.status(f"[red]{self.fighter_a} typing...[/red]"):
            t_a = self.get_fighter_response(self.fighter_a, p_a)
        console.print(Panel(Markdown(t_a), title=f"🔴 {self.fighter_a}", border_style="red"))
        self.history.append({"role": "user", "content": t_a, "fighter": "red"})

        # Turn B
        p_b = f"Topic: {self.topic}. Position: AGAINST. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{t_a}'. Rebut."
        with console.status(f"[blue]{self.fighter_b} typing...[/blue]"):
            t_b = self.get_fighter_response(self.fighter_b, p_b)
        console.print(Panel(Markdown(t_b), title=f"🔵 {self.fighter_b}", border_style="blue"))
        self.history.append({"role": "user", "content": t_b, "fighter": "blue"})

        return t_a, t_b

    def score_round(self, round_num, t_a, t_b, countdown_fn):
        """Judges the round and updates state."""
        console.print("[dim]Judges are deciding...[/dim]")
        countdown_fn(30, "Judges Deliberating")
        
        round_verdicts = []
        red_round_wins = 0
        blue_round_wins = 0
        
        console.print("[bold yellow]VERDICTS:[/bold yellow]")
        for idx, j in enumerate(self.judges):
            with console.status(f"[yellow]Judge {idx+1} judging...[/yellow]"):
                v = get_single_judge_verdict(j, self.topic, t_a, t_b)
            
            if v['score_a'] > v['score_b']: red_round_wins += 1
            elif v['score_b'] > v['score_a']: blue_round_wins += 1
            
            self.total_red_score += v['score_a']
            self.total_blue_score += v['score_b']
            
            if v['score_a'] > v['score_b']: self.judge_round_wins[j]["red"] += 1
            elif v['score_b'] > v['score_a']: self.judge_round_wins[j]["blue"] += 1
            
            s_a_col = "green" if v['score_a'] > v['score_b'] else "white"
            s_b_col = "green" if v['score_b'] > v['score_a'] else "white"
            console.print(f"[dim]{j.split('/')[-1]}[/dim]: A:[{s_a_col}]{v['score_a']}[/{s_a_col}] B:[{s_b_col}]{v['score_b']}[/{s_b_col}] - {v['reason']}")
            round_verdicts.append(v)

        if red_round_wins > blue_round_wins: 
            console.print(f"\n[bold red] ROUND {round_num} WINNER: RED ({red_round_wins}-{blue_round_wins})[/bold red]")
        elif blue_round_wins > red_round_wins: 
            console.print(f"\n[bold blue] ROUND {round_num} WINNER: BLUE ({blue_round_wins}-{red_round_wins})[/bold blue]")
        else: 
            console.print(f"\n[bold yellow] ROUND {round_num} RESULT: DRAW[/bold yellow]")

        self.fight_data["rounds"].append({
            "round": round_num, 
            "red_text": t_a, 
            "blue_text": t_b, 
            "verdicts": round_verdicts
        })

    def run_sudden_death(self, countdown_fn):
        """Runs a sudden death round if the match is a draw."""
        console.print(Rule("SUDDEN DEATH", style="bold red"))
        sd_prompt = "SUDDEN DEATH: Why do you deserve to win this fight? Be ruthless."
        
        with console.status(f"[red]{self.fighter_a} SUDDEN DEATH...[/red]"):
            t_a = self.get_fighter_response(self.fighter_a, sd_prompt)
        console.print(Panel(Markdown(t_a), title=f"🔴 {self.fighter_a} (SD)", border_style="red"))
        
        with console.status(f"[blue]{self.fighter_b} SUDDEN DEATH...[/blue]"):
            t_b = self.get_fighter_response(self.fighter_b, sd_prompt)
        console.print(Panel(Markdown(t_b), title=f"🔵 {self.fighter_b} (SD)", border_style="blue"))
        
        countdown_fn(60, "Final Deliberation")
        sd_red, sd_blue = 0, 0
        for idx, j in enumerate(self.judges):
            v = get_single_judge_verdict(j, "SUDDEN DEATH", t_a, t_b)
            if v['score_a'] >= v['score_b']:
                if v['score_a'] == v['score_b']: v['score_a'] += 1
                sd_red += 1
                winner_col = "red"
            else: 
                sd_blue += 1
                winner_col = "blue"
            console.print(f"Judge {idx+1} SD Vote: [{winner_col}]{winner_col.upper()}[/{winner_col}]")
        
        winner = "red" if sd_red > sd_blue else "blue"
        return winner

    def resolve_winner(self):
        """Finalize scores and determine overall winner."""
        self.fight_data["aggregate_scores"] = {"red": self.total_red_score, "blue": self.total_blue_score}
        judge_winners = []
        for j in self.judges:
            r_sum = sum(r["verdicts"][self.judges.index(j)]["score_a"] for r in self.fight_data["rounds"])
            b_sum = sum(r["verdicts"][self.judges.index(j)]["score_b"] for r in self.fight_data["rounds"])
            if r_sum > b_sum: judge_winners.append("red")
            elif b_sum > r_sum: judge_winners.append("blue")
            else: judge_winners.append("draw")

        red_wins, blue_wins = judge_winners.count("red"), judge_winners.count("blue")
        return red_wins, blue_wins
