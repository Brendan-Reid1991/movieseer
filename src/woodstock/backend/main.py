from fastapi import FastAPI

from woodstock.backend.services import RadarrRouter

app = FastAPI()

app.include_router(RadarrRouter)
