from functools import lru_cache

from app.clients.ai_base import AIClient
from app.clients.places_base import PlaceProvider
from app.core.config import get_settings


@lru_cache
def get_ai_client() -> AIClient:
    settings = get_settings()
    if settings.ai_mode == "mock":
        from app.clients.mock_ai import MockAIClient
        return MockAIClient()
    from app.clients.claude_client import ClaudeClient
    return ClaudeClient(settings)


@lru_cache
def get_place_provider() -> PlaceProvider:
    settings = get_settings()
    if settings.place_provider == "mock":
        from app.clients.mock_places import MockPlaceProvider
        return MockPlaceProvider()
    from app.clients.kakao_places import KakaoPlaceProvider
    return KakaoPlaceProvider(settings.kakao_rest_api_key)
