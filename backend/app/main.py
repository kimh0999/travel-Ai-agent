import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.clients.ai_base import AIError
from app.core.config import get_settings
from app.core.errors import error_body, register_error_handlers
from app.routers import conversations, feedback, health, me, preferences, proposals, trips

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI 여행 비서 API", version="1.0.0", docs_url="/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)

    @app.exception_handler(AIError)
    async def _ai_error(_, exc: AIError):
        # AI 실패는 저장 전에 발생하므로 입력·기존 코스는 그대로다.
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code)

    for r in (health.router, me.router, preferences.router, trips.router, feedback.router, proposals.router,
              conversations.router):
        app.include_router(r)
    return app


app = create_app()
