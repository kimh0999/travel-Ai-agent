"""환경변수 기반 설정. 서버 비밀값은 여기서만 읽고 응답에 절대 포함하지 않는다."""
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    claude_model: str
    claude_effort: str
    ai_timeout: float
    ai_max_retries: int
    firebase_service_account_json: str
    firebase_project_id: str
    cors_origins: list[str]
    kakao_rest_api_key: str
    ai_mode: str
    place_provider: str

    @property
    def use_emulator(self) -> bool:
        return bool(os.getenv("FIRESTORE_EMULATOR_HOST"))


def _choice(name: str, default: str, allowed: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in allowed:
        raise RuntimeError(f"{name} must be one of {sorted(allowed)}, got '{value}'")
    return value


@lru_cache
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip(),
        claude_effort=_choice("CLAUDE_EFFORT", "medium", {"low", "medium", "high", "xhigh", "max"}),
        ai_timeout=float(os.getenv("AI_TIMEOUT", "120")),
        ai_max_retries=int(os.getenv("AI_MAX_RETRIES", "2")),
        firebase_service_account_json=os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", ""),
        firebase_project_id=os.getenv("FIREBASE_PROJECT_ID", ""),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        kakao_rest_api_key=os.getenv("KAKAO_REST_API_KEY", ""),
        ai_mode=_choice("AI_MODE", "mock", {"live", "mock"}),
        place_provider=_choice("PLACE_PROVIDER", "mock", {"kakao", "mock"}),
    )
