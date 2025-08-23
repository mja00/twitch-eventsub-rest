from fastapi import APIRouter
from app.storage import get_storage
from app.analytics import analytics_service

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Twitch EventSub REST API"}


@router.get("/health")
async def health_check():
    storage = get_storage()
    storage_status = await storage.health_check()
    mongodb_status = await analytics_service.health_check()

    overall_healthy = storage_status and mongodb_status

    return {
        "status": "healthy" if overall_healthy else "unhealthy",
        "storage": "connected" if storage_status else "disconnected",
        "mongodb": "connected" if mongodb_status else "disconnected",
    }
