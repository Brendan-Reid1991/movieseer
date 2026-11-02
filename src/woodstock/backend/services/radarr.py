from fastapi import APIRouter

from woodstock.service_apis.radarr import RadarrClient

router = APIRouter(prefix="/radarr", tags=["Radarr"])


@router.get("/recent_history")
async def fetch_radarr_recents(recents: int = 5):
    client = RadarrClient()
    history = await client.history()
    return history[:recents]
