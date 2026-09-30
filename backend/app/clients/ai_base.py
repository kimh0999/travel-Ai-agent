from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    status_code = 502
    code = "AI_FAILED"

    def __init__(self, message: str = "AI 응답을 받지 못했습니다. 입력 내용은 그대로 있으니 다시 시도하세요."):
        super().__init__(message)
        self.message = message


class AITimeout(AIError):
    status_code = 504
    code = "AI_TIMEOUT"

    def __init__(self, message: str = "AI 응답 시간이 초과되었습니다. 입력 내용과 기존 코스는 그대로 있어요."):
        super().__init__(message)


class AIInvalidResponse(AIError):
    """구조화 응답이 Pydantic 검증을 통과하지 못함 (파이프라인이 1회 재시도)."""


class AIRefusal(AIError):
    pass


# ---------------- 에이전트 대화 턴 ----------------

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]


@dataclass
class TurnResult:
    reply: str
    tool_calls: list[str] = field(default_factory=list)


# (도구 이름, JSON 인자 문자열) → JSON 결과 문자열. 인자 검증·소유자 검사는 서버 실행기가 한다.
ToolExecutor = Callable[[str, str], str]
# 화면으로 보낼 이벤트(예: {"type": "text", "delta": "..."}).
Emit = Callable[[dict[str, Any]], None]
# 도구 실행·모델 응답마다 호출된다. 대화 기록(transcript)을 저장해 두면 중단 후 이어서 실행할 수 있다.
OnStep = Callable[[list[dict[str, Any]]], None]


class AIClient(Protocol):
    name: str
    model: str
    is_mock: bool

    def parse(self, *, kind: str, system: str, user: str, schema: type[T], context: Any, timeout: float) -> T:
        """system/user 프롬프트로 구조화 응답을 받아 schema로 검증해 반환한다.

        kind: "course" | "proposals". context는 프롬프트를 만든 구조화 데이터(모의 구현이 사용)."""
        ...

    def run_turn(self, *, system: str, transcript: list[dict[str, Any]], tools: list[ToolSpec],
                 execute: ToolExecutor, emit: Emit, on_step: OnStep, deadline: float,
                 max_tool_calls: int) -> TurnResult:
        """transcript를 이어서 에이전트 턴을 끝까지 실행한다.

        transcript는 JSON으로 저장 가능한 메시지 목록이며, 이전 시도에서 저장한 것을 그대로 넘기면
        이미 실행한 도구는 다시 실행하지 않고 이어서 진행한다. 도구는 tools 목록만, execute로만 실행된다."""
        ...


def reply_from_transcript(transcript: list[dict[str, Any]]) -> str:
    """이번 턴에서 모델이 쓴 텍스트(목록 형태 content의 text 블록)를 순서대로 합친다."""
    parts = []
    for m in transcript:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            parts += [b.get("text", "") for b in m["content"] if b.get("type") == "text"]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
