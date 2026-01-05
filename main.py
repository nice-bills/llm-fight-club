import sys
import os
import litellm
import asyncio

# Suppress LiteLLM logging to keep UI clean
litellm.set_verbose = False
litellm.suppress_debug_info = True

# Ensure src is in python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from llm_fight_club.engine import run_fight_loop

if __name__ == "__main__":
    asyncio.run(run_fight_loop())