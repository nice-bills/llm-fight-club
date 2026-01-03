import re
import json
import random
import time
from litellm import completion
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

def get_single_judge_verdict(judge_model, topic, text_a, text_b, retries=2):
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
    
    for attempt in range(retries + 1):
        try:
            response = completion(
                model=judge_model,
                messages=[{"role": "user", "content": judge_prompt}],
                max_tokens=500,
                timeout=180,
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
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback Regex
                s_a = re.search(r"score_a.*?(\d+)", content, re.IGNORECASE)
                s_b = re.search(r"score_b.*?(\d+)", content, re.IGNORECASE)
                reason = re.search(r'reason.*?["\':](.*?)["}]', content, re.IGNORECASE | re.DOTALL)
                
                val_a = int(s_a.group(1)) if s_a else 5
                val_b = int(s_b.group(1)) if s_b else 5
                
                return {
                    "judge": judge_model,
                    "score_a": val_a,
                    "score_b": val_b,
                    "reason": reason.group(1).strip() if (reason and reason.group(1)) else "Parse error."
                }
        except Exception as e:
            if attempt == retries:
                return {"judge": judge_model, "score_a": 5, "score_b": 5, "reason": f"Error: {str(e)[:50]}"}
            time.sleep(2)
            
    return {"judge": judge_model, "score_a": 5, "score_b": 5, "reason": "Timeout/Error"}
