from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from aggregator import Aggregator
import notifier

app = FastAPI()
aggregator = Aggregator()


@app.get("/")
async def dashboard():
    return FileResponse("templates/index.html")


@app.get("/api/status")
async def api_status():
    return await aggregator.get_status()


@app.post("/webhook/radarr")
async def radarr_webhook(request: Request):
    payload = await request.json()
    aggregator.invalidate_cache()
    await notifier.handle_radarr(payload)
    return {"ok": True}


@app.post("/webhook/sonarr")
async def sonarr_webhook(request: Request):
    payload = await request.json()
    aggregator.invalidate_cache()
    await notifier.handle_sonarr(payload)
    return {"ok": True}
