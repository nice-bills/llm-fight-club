import sys
import os
import uvicorn

# Ensure src is in python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from llm_fight_club.api.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
