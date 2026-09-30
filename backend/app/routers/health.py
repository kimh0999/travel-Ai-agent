from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    # 콜드 스타트 대응용. 인증 불필요, Firestore·Claude를 호출하지 않는다.
    s = get_settings()
    return {"status": "ok", "ai_mode": s.ai_mode, "place_provider": s.place_provider}
