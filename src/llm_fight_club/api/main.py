import json
import asyncio
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from llm_fight_club.core.fight import FightManager
from llm_fight_club.core.models import load_models, get_model_lab
from llm_fight_club.core.judging import JudgeRotation
from litellm import acompletion 

app = FastAPI(title="AI Fight Club API")

async def generate_topic():
    try:
        resp = await acompletion(
            model="groq/llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Generate ONE controversial debate topic. Single question."}],
            max_tokens=60
        )
        return resp.choices[0].message.content.strip().replace('"', '')
    except:
        return "Should AI be granted legal personhood?"

@app.get("/")
async def root():
    return {"status": "AI Fight Club API is live"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        # 1. Load pool and verify models
        all_models = load_models()
        if len(all_models) < 5:
            await websocket.send_json({"type": "error", "data": {"message": "Not enough models in pool."}})
            return

        # 2. Matchup Selection
        fighter_a = random.choice(all_models)
        lab_a = get_model_lab(fighter_a)
        remaining_for_b = [m for m in all_models if get_model_lab(m) != lab_a and m != fighter_a]
        if not remaining_for_b: remaining_for_b = [m for m in all_models if m != fighter_a]
        fighter_b = random.choice(remaining_for_b)
        
        rotator = JudgeRotation(all_models)
        judges = rotator.get_judges([fighter_a, fighter_b])
        topic = await generate_topic()
        
        # 3. Event Callback for WebSocket
        async def on_fight_event(event_type, data):
            payload = {"type": event_type, "data": data}
            await websocket.send_text(json.dumps(payload))
        
        # 4. Initialize Manager
        manager = FightManager(
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            judges=judges,
            topic=topic,
            sys_prompt="You are a ruthless debater. Attack logic. Max 3 sentences.",
            on_event=on_fight_event
        )
        
        # 5. Broadcast Initial State
        await on_fight_event("fight_init", {
            "id": manager.fight_id,
            "topic": topic,
            "fighter_a": fighter_a,
            "fighter_b": fighter_b,
            "judges": judges
        })
        
        # 6. Run 5 Rounds
        for round_num in range(1, 6):
            t_a, t_b = await manager.run_round(round_num)
            await manager.score_round(round_num, t_a, t_b)
            
            if round_num < 5:
                await on_fight_event("intermission", {"duration": 120})
                await asyncio.sleep(120) 

        # 7. Finalize
        red_wins, blue_wins = manager.resolve_winner()
        winner_key = "red" if red_wins > blue_wins else "blue"
        
        if red_wins == blue_wins:
            winner_key = await manager.run_sudden_death()
            res = "Sudden Death"
        else:
            res = "Unanimous" if (red_wins==3 or blue_wins==3) else "Split"
            
        await on_fight_event("fight_complete", {
            "winner": winner_key,
            "winner_name": fighter_a if winner_key == "red" else fighter_b,
            "decision": res,
            "score": f"{manager.total_red_score}-{manager.total_blue_score}"
        })
        manager.save_result()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "data": {"message": str(e)}})
        except: pass