"""구조화 AI 호출 공통 처리: 시간 예산 안에서 호출하고, 응답 검증 실패 시 1회만 재시도한다."""
import logging
import time
from typing import Any, Optional

from app.clients.ai_base import AIError, AIInvalidResponse, T
from app.clients.factory import get_ai_client
from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger("app.ai")

BUDGET_SECONDS = 150
MIN_RETRY_SECONDS = 30


def call_structured(kind: str, system: str, user: str, schema: type[T], context: Any,
                    started: Optional[float] = None) -> T:
    started = started if started is not None else time.monotonic()
    client = get_ai_client()
    timeout_setting = get_settings().ai_timeout
    last_error: Optional[AIError] = None
    for attempt in range(2):
        remaining = BUDGET_SECONDS - (time.monotonic() - started)
        if attempt > 0 and remaining < MIN_RETRY_SECONDS:
            break
        try:
            return client.parse(kind=kind, system=system, user=user, schema=schema, context=context,
                                timeout=max(5.0, min(timeout_setting, remaining)))
        except AIInvalidResponse as e:
            logger.warning("AI invalid response kind=%s attempt=%d: %s", kind, attempt + 1, e)
            last_error = e
    raise AppError(502, "AI_FAILED", (last_error.message if last_error else "AI 응답이 올바르지 않습니다.")
                   + " 다시 시도해 주세요. 입력 내용과 기존 데이터는 그대로 있어요.")
