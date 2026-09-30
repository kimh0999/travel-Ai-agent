"""Claude Messages API 클라이언트 (anthropic Python SDK 1.x).

- 구조화 출력: beta.messages.stream(output_format=Pydantic 모델) → parsed_output. 검증 실패는 AIInvalidResponse.
- 에이전트 턴: 도구 호출 루프를 직접 돌린다. 모델 응답과 도구 결과를 transcript에 이어 붙이고(append-only)
  단계마다 on_step으로 저장한다. 저장된 transcript를 넘기면 이미 실행한 도구는 다시 실행하지 않는다.
- 거절(stop_reason=refusal) 대비로 서버 측 fallback("default")을 켠다.
"""
import json
import time
from typing import Any

import anthropic
from pydantic import ValidationError

from app.clients.ai_base import (AIError, AIInvalidResponse, AIRefusal, AITimeout, Emit, OnStep, T, ToolExecutor,
                                 ToolSpec, TurnResult, reply_from_transcript)
from app.core.config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
CHAT_MAX_TOKENS = 32000
PARSE_MAX_TOKENS = 32000
MAX_JSON_RETRIES = 2


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic JSON 스키마의 $defs/$ref를 펼쳐 도구 input_schema로 쓴다."""
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def tool_definition(spec: ToolSpec) -> dict[str, Any]:
    return {"name": spec.name, "description": spec.description,
            "input_schema": _inline_refs(spec.args_model.model_json_schema()),
            "eager_input_streaming": True}


def _dump_block(block: Any) -> dict[str, Any]:
    return block.model_dump(mode="json", exclude_none=True)


class ClaudeClient:
    name = "claude"
    is_mock = False

    def __init__(self, settings: Settings):
        self.model = settings.claude_model
        self.effort = settings.claude_effort
        # ANTHROPIC_API_KEY가 비어 있으면 SDK의 기본 자격증명 탐색(ant auth login 프로필 등)을 따른다.
        kwargs: dict[str, Any] = {"timeout": settings.ai_timeout, "max_retries": settings.ai_max_retries}
        if settings.anthropic_api_key:
            kwargs["api_key"] = settings.anthropic_api_key
        self._client = anthropic.Anthropic(**kwargs)

    def _common(self) -> dict[str, Any]:
        return {"model": self.model, "output_config": {"effort": self.effort},
                "betas": [FALLBACK_BETA], "fallbacks": "default"}

    @staticmethod
    def _wrap(e: Exception) -> AIError:
        if isinstance(e, anthropic.APITimeoutError):
            return AITimeout()
        if isinstance(e, anthropic.RateLimitError):
            return AIError("AI 요청이 많아 잠시 처리하지 못했어요. 잠시 후 다시 시도하세요.")
        if isinstance(e, anthropic.AuthenticationError):
            return AIError("AI 서비스 인증에 실패했습니다. 서버의 ANTHROPIC_API_KEY 설정을 확인하세요.")
        if isinstance(e, anthropic.APIConnectionError):
            return AIError("AI 서비스에 연결하지 못했습니다. 다시 시도하세요.")
        return AIError(f"AI 서비스 오류로 응답을 받지 못했습니다 ({e.__class__.__name__}). 다시 시도하세요.")

    def parse(self, *, kind: str, system: str, user: str, schema: type[T], context: Any, timeout: float) -> T:
        try:
            with self._client.with_options(timeout=timeout).beta.messages.stream(
                **self._common(), max_tokens=PARSE_MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": user}], output_format=schema,
            ) as stream:
                message = stream.get_final_message()
        except ValidationError as e:
            raise AIInvalidResponse("AI 응답 형식이 올바르지 않습니다.") from e
        except anthropic.APIError as e:
            raise self._wrap(e) from e
        if message.stop_reason == "refusal":
            raise AIRefusal("AI가 이 요청에 응답하지 않았습니다. 입력을 바꿔 다시 시도하세요.")
        if message.stop_reason == "max_tokens":
            raise AIInvalidResponse("AI 응답이 너무 길어 잘렸습니다.")
        parsed = message.parsed_output
        if parsed is None:
            raise AIInvalidResponse("AI 응답이 비어 있습니다.")
        return parsed

    def _call(self, system: str, messages: list[dict[str, Any]], tool_defs: list[dict[str, Any]],
              allow_tools: bool, emit: Emit, deadline: float):
        for attempt in range(MAX_JSON_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise AITimeout("AI 처리 시간을 넘었습니다. 지금까지 진행한 내용은 저장되어 있어요. 다시 시도하세요.")
            try:
                with self._client.with_options(timeout=remaining).beta.messages.stream(
                    **self._common(), max_tokens=CHAT_MAX_TOKENS, system=system, messages=messages,
                    tools=tool_defs, tool_choice={"type": "auto" if allow_tools else "none"},
                ) as stream:
                    for event in stream:
                        if event.type == "text":
                            emit({"type": "text", "delta": event.text})
                    return stream.get_final_message()
            except ValueError:
                # 도구 입력 JSON을 전혀 해석할 수 없는 경우(eager input streaming). 같은 요청을 다시 보낸다.
                if attempt >= MAX_JSON_RETRIES:
                    raise AIInvalidResponse("AI가 올바르지 않은 도구 입력을 보냈습니다.")
                emit({"type": "text_reset"})
            except anthropic.APIError as e:
                raise self._wrap(e) from e
        raise AIInvalidResponse("AI 응답을 받지 못했습니다.")

    def run_turn(self, *, system: str, transcript: list[dict[str, Any]], tools: list[ToolSpec],
                 execute: ToolExecutor, emit: Emit, on_step: OnStep, deadline: float,
                 max_tool_calls: int) -> TurnResult:
        tool_defs = [tool_definition(t) for t in tools]
        messages = list(transcript)
        called = [b["name"] for m in messages if m["role"] == "assistant" and isinstance(m["content"], list)
                  for b in m["content"] if b.get("type") == "tool_use"]
        paused = False
        while True:
            last = messages[-1]
            if last["role"] == "assistant" and not paused:
                tool_uses = [b for b in last["content"] if b.get("type") == "tool_use"]
                if not tool_uses:
                    return TurnResult(reply=reply_from_transcript(messages), tool_calls=called)
                results = []
                for block in tool_uses:
                    output = execute(block["name"], json.dumps(block.get("input") or {}, ensure_ascii=False))
                    is_error = "error" in json.loads(output)
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "content": output,
                                    **({"is_error": True} if is_error else {})})
                messages.append({"role": "user", "content": results})
                on_step(messages)
                continue

            message = self._call(system, messages, tool_defs, len(called) < max_tool_calls, emit, deadline)
            if message.stop_reason == "refusal":
                raise AIRefusal("AI가 이 요청에 응답하지 않았습니다. 표현을 바꿔 다시 시도하세요.")
            content = [_dump_block(b) for b in message.content]
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if message.stop_reason == "max_tokens" and tool_uses:
                raise AIInvalidResponse("AI 응답이 길어 도구 입력이 잘렸습니다. 요청을 나눠서 다시 시도하세요.")
            messages.append({"role": "assistant", "content": content})
            called += [b["name"] for b in tool_uses]
            on_step(messages)
            paused = message.stop_reason == "pause_turn"
