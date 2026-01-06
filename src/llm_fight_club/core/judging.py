import re
import os
import json
import random
import asyncio
import ast
import time
from litellm import acompletion
from llm_fight_club.utils.text import clean_text

class JudgeRotation:
    def __init__(self, model_pool):
        self.pool = list(set(model_pool))
        self.rotation_index = 0
        random.shuffle(self.pool)
    
    def get_judges(self, fighters):
        """Pick 3 unique judges, prioritizing provider diversity."""
        judges = []
        
        # Categorize pool by provider
        providers = {}
        for m in self.pool:
            p = m.split('/')[0]
            if p not in providers: 
                providers[p] = []
            providers[p].append(m)
            
        # Try to pick 1 from each provider first (Diversity)
        active_providers = list(providers.keys())
        random.shuffle(active_providers)
        
        for p in active_providers:
            if len(judges) >= 3: 
                break
            candidates = [m for m in providers[p] if m not in fighters and m not in judges]
            if candidates:
                judges.append(random.choice(candidates))
        
        # Fill the rest using rotation index
        attempts = 0
        while len(judges) < 3 and attempts < len(self.pool) * 2:
            judge = self.pool[self.rotation_index % len(self.pool)]
            if judge not in fighters and judge not in judges:
                judges.append(judge)
            self.rotation_index += 1
            attempts += 1
            
        return judges

async def get_single_judge_verdict(judge_model, topic, text_a, text_b, retries=2):
    """Call a single judge and parse their verdict with retries and fallback."""
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
    
    # Prepare Minimax params if needed
    kwargs = {
        "messages": [{"role": "user", "content": judge_prompt}],
        "max_tokens": 500,
        "timeout": 180
    }
    
    if "minimax" in judge_model.lower():
        kwargs["model"] = "openai/" + judge_model.split("/")[-1]
        kwargs["api_base"] = "https://api.minimax.io/v1"
        kwargs["api_key"] = os.getenv("MINIMAX_API_KEY")
        kwargs["temperature"] = 1.0
    else:
        kwargs["model"] = judge_model
        if any(p in judge_model for p in ["groq", "mistral", "openai"]):
            kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(retries + 1):
        try:
            response = await acompletion(**kwargs)
            content = response.choices[0].message.content
            
            try:
                data = json.loads(content)
                s_a = int(data.get("score_a", 5))
                s_b = int(data.get("score_b", 5))
                
                # Handle nested reason objects (Mistral quirk)
                reason_raw = data.get("reason", "No reason.")
                if isinstance(reason_raw, dict):
                    # Flatten dict values into string
                    reason = " ".join([str(v) for v in reason_raw.values()])
                elif isinstance(reason_raw, str) and reason_raw.strip().startswith("{"):
                    # Handle stringified dict
                    try:
                        import ast
                        r_dict = ast.literal_eval(reason_raw)
                        if isinstance(r_dict, dict):
                             reason = " ".join([str(v) for v in r_dict.values()])
                        else:
                             reason = reason_raw
                    except:
                        reason = reason_raw
                else:
                    reason = str(reason_raw)
                
                # Tie-breaker: No 5-5 allowed
                if s_a == s_b:
                    if random.choice([True, False]): s_a += 1
                    else: s_b += 1
                
                return {
                    "judge": judge_model,
                    "score_a": s_a,
                    "score_b": s_b,
                    "reason": reason
                }
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback 1: AST Literal Eval (for Python dicts)
                try:
                    # Finds the largest {...} block
                    dict_match = re.search(r"(\{.*\})", content, re.DOTALL)
                    if dict_match:
                        data = ast.literal_eval(dict_match.group(1))
                        s_a = int(data.get("score_a", 5))
                        s_b = int(data.get("score_b", 5))
                        
                        raw_reason = data.get("reason", "No reason.")
                        if isinstance(raw_reason, dict):
                            reason = " ".join([str(v) for v in raw_reason.values()])
                        else:
                            reason = str(raw_reason)
                            
                        # Tie-breaker
                        if s_a == s_b:
                            if random.choice([True, False]): s_a += 1
                            else: s_b += 1
                            
                        return {"judge": judge_model, "score_a": s_a, "score_b": s_b, "reason": reason}
                except:
                    pass

                # Fallback 2: Regex
                s_a = re.search(r"score_a.*?(\d+)", content, re.IGNORECASE)
                s_b = re.search(r"score_b.*?(\d+)", content, re.IGNORECASE)
                
                # Try to catch reason text, avoiding nested brackets if possible
                reason = re.search(r'reason.*?["\':]\s*"?([^"{}]+)"?', content, re.IGNORECASE | re.DOTALL)
                
                val_a = int(s_a.group(1)) if s_a else 5
                val_b = int(s_b.group(1)) if s_b else 5
                
                if val_a == val_b:
                    if random.choice([True, False]): val_a += 1
                    else: val_b += 1
                
                return {
                    "judge": judge_model,
                    "score_a": val_a,
                    "score_b": val_b,
                    "reason": reason.group(1).strip() if (reason and reason.group(1)) else content[:150].replace("\n", " ")
                }
        except Exception as e:
            if attempt == retries:
                return {"judge": judge_model, "score_a": 5, "score_b": 5, "reason": f"Error: {str(e)[:50]}"}
            time.sleep(2)
            
    return {"judge": judge_model, "score_a": 5, "score_b": 5, "reason": "Timeout/Error"}
