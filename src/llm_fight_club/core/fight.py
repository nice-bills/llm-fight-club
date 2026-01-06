import os
import json
import random
import asyncio
import time
from datetime import datetime
from litellm import acompletion
from rich.console import Console # Kept only for internal debugging if needed, but not used for main output

from llm_fight_club.utils.text import clean_text
from llm_fight_club.core.models import get_model_lab
from llm_fight_club.core.judging import get_single_judge_verdict

class FightManager:
    def __init__(self, fighter_a, fighter_b, judges, topic, sys_prompt, on_event=None):
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.judges = judges
        self.topic = topic
        self.sys_prompt = sys_prompt
        self.on_event = on_event  # Callback function(event_type, data)
        
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

    async def _emit(self, event_type, data):
        """Send event to callback if registered."""
        if self.on_event:
            if asyncio.iscoroutinefunction(self.on_event):
                await self.on_event(event_type, data)
            else:
                self.on_event(event_type, data)

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
        if not os.path.exists("results"):
            os.makedirs("results")
        filename = f"results/fight_{self.fight_id}.json"
        with open(filename, "w") as f:
            json.dump(self.fight_data, f, indent=2)

    async def run_round(self, round_num):
        await self._emit("round_start", {"round": round_num})
        
        # Turn A
        p_a = f"Topic: {self.topic}. Position: FOR. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{self.history[-1]['content']}'. Rebut."
        await self._emit("fighter_thinking", {"fighter": "red", "model": self.fighter_a})
        t_a = await self.get_fighter_response(self.fighter_a, p_a)
        await self._emit("fighter_speaking", {"fighter": "red", "model": self.fighter_a, "text": t_a})
        self.history.append({"role": "user", "content": t_a, "fighter": "red"})

        # Turn B
        p_b = f"Topic: {self.topic}. Position: AGAINST. Opening statement. Do not refer to an opponent yet." if round_num == 1 else f"Opponent: '{t_a}'. Rebut."
        await self._emit("fighter_thinking", {"fighter": "blue", "model": self.fighter_b})
        t_b = await self.get_fighter_response(self.fighter_b, p_b)
        await self._emit("fighter_speaking", {"fighter": "blue", "model": self.fighter_b, "text": t_b})
        self.history.append({"role": "user", "content": t_b, "fighter": "blue"})

        return t_a, t_b

    async def score_round(self, round_num, t_a, t_b):
        await self._emit("judging_start", {})
        
        # Run judges in parallel
        judge_tasks = [get_single_judge_verdict(j, self.topic, t_a, t_b) for j in self.judges]
        verdicts = await asyncio.gather(*judge_tasks)
        
        round_verdicts = []
        red_round_wins = 0
        blue_round_wins = 0
        
        for idx, v in enumerate(verdicts):
            j_name = self.judges[idx]
            
            if v['score_a'] > v['score_b']: red_round_wins += 1
            elif v['score_b'] > v['score_a']: blue_round_wins += 1
            
            self.total_red_score += v['score_a']
            self.total_blue_score += v['score_b']
            
            if v['score_a'] > v['score_b']: self.judge_round_wins[j_name]["red"] += 1
            elif v['score_b'] > v['score_a']: self.judge_round_wins[j_name]["blue"] += 1
            
            # Emit individual verdict event
            await self._emit("verdict_received", {
                "judge_index": idx,
                "judge_model": j_name,
                "score_a": v['score_a'],
                "score_b": v['score_b'],
                "reason": v['reason']
            })
            round_verdicts.append(v)

        winner = "draw"
        if red_round_wins > blue_round_wins: winner = "red"
        elif blue_round_wins > red_round_wins: winner = "blue"
        
        await self._emit("round_result", {
            "round": round_num,
            "winner": winner,
            "score_red": red_round_wins,
            "score_blue": blue_round_wins
        })

        self.fight_data["rounds"].append({
            "round": round_num, 
            "red_text": t_a, 
            "blue_text": t_b, 
            "verdicts": round_verdicts
        })

    async def run_sudden_death(self):
        await self._emit("sudden_death_start", {})
        sd_prompt = "SUDDEN DEATH: Why do you deserve to win this fight? Be ruthless."
        
        await self._emit("fighter_thinking", {"fighter": "red", "model": self.fighter_a})
        t_a = await self.get_fighter_response(self.fighter_a, sd_prompt)
        await self._emit("fighter_speaking", {"fighter": "red", "model": self.fighter_a, "text": t_a})
        
        await self._emit("fighter_thinking", {"fighter": "blue", "model": self.fighter_b})
        t_b = await self.get_fighter_response(self.fighter_b, sd_prompt)
        await self._emit("fighter_speaking", {"fighter": "blue", "model": self.fighter_b, "text": t_b})
        
        await self._emit("judging_start", {"mode": "sudden_death"})
        
        sd_tasks = [get_single_judge_verdict(j, "SUDDEN DEATH", t_a, t_b) for j in self.judges]
        sd_verdicts = await asyncio.gather(*sd_tasks)
        
        sd_red, sd_blue = 0, 0
        for idx, v in enumerate(sd_verdicts):
            winner_col = "red"
            if v['score_a'] >= v['score_b']:
                if v['score_a'] == v['score_b']: v['score_a'] += 1
                sd_red += 1
            else: 
                sd_blue += 1
                winner_col = "blue"
            
            await self._emit("verdict_received", {
                "judge_index": idx,
                "judge_model": self.judges[idx],
                "score_a": v['score_a'],
                "score_b": v['score_b'],
                "reason": v['reason'],
                "sd_vote": winner_col
            })
        
        return "red" if sd_red > sd_blue else "blue"

    def resolve_winner(self):
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