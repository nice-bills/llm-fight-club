from fastapi import FastAPI

app = FastAPI(title="AI Fight Club API")

@app.get("/")
async def root():
    return {"status": "AI Fight Club API is live"}

@app.get("/health")
async def health():
    return {"status": "healthy"}
