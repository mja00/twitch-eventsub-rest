from fastapi import APIRouter
from app.storage import get_storage

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Twitch EventSub REST API"}


@router.get("/health")
async def health_check():
    storage = get_storage()
    storage_status = await storage.health_check()
    return {
        "status": "healthy" if storage_status else "unhealthy",
        "storage": "connected" if storage_status else "disconnected",
    }
