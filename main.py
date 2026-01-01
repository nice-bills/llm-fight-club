import sys
import os

# Ensure src is in python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from llm_fight_club.engine import run_fight_loop

if __name__ == "__main__":
    run_fight_loop()