"""ClaudeClient의 도구 호출 루프와 도구 스키마 (API를 부르지 않고 응답을 흉내 낸다).

실제 Claude 연결은 키가 필요하므로 scripts/check_live_claude.py로 따로 확인한다."""
import json
from types import SimpleNamespace

import pytest

from app.clients.ai_base import AIRefusal
from app.clients.claude_client import ClaudeClient, tool_definition
from app.core.config import get_settings
from app.services.agent_tools import TOOLS


class Block(SimpleNamespace):
    def model_dump(self, **kw):
        return {k: v for k, v in vars(self).items() if v is not None}


def _msg(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


def _client(monkeypatch, responses):
    client = ClaudeClient(get_settings())
    sent = []

    def fake_call(system, messages, tool_defs, allow_tools, emit, deadline):
        sent.append({"messages": json.loads(json.dumps(messages)), "allow_tools": allow_tools})
        return responses.pop(0)

    monkeypatch.setattr(client, "_call", fake_call)
    return client, sent


def _run(client, transcript, execute, steps, max_tool_calls=5):
    return client.run_turn(system="s", transcript=transcript, tools=TOOLS, execute=execute, emit=lambda e: None,
                           on_step=lambda m: steps.append(json.loads(json.dumps(m))), deadline=1e12,
                           max_tool_calls=max_tool_calls)


def test_tool_schemas_are_self_contained():
    for spec in TOOLS:
        d = tool_definition(spec)
        text = json.dumps(d)
        assert "$ref" not in text and "$defs" not in text
        assert d["input_schema"]["type"] == "object" and d["eager_input_streaming"] is True
    revise = next(tool_definition(t) for t in TOOLS if t.name == "revise_course")
    item = revise["input_schema"]["properties"]["days"]["items"]["properties"]["items"]["items"]
    assert {"start_time", "stay_minutes", "backup"} <= set(item["properties"])


def test_tool_loop_executes_tools_and_saves_each_step(monkeypatch):
    client, sent = _client(monkeypatch, [
        _msg("tool_use", Block(type="tool_use", id="tu1", name="list_trips", input={})),
        _msg("end_turn", Block(type="text", text="여행이 없어요.")),
    ])
    executed, steps = [], []

    def execute(name, raw):
        executed.append((name, json.loads(raw)))
        return json.dumps({"trips": []})

    result = _run(client, [{"role": "user", "content": "여행 있어?"}], execute, steps)
    assert result.reply == "여행이 없어요." and result.tool_calls == ["list_trips"]
    assert executed == [("list_trips", {})]
    assert sent[1]["messages"][-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu1", "content": '{"trips": []}'}]}
    assert len(steps) == 3  # 모델 응답 → 도구 결과 → 최종 답변마다 저장


def test_resume_runs_only_pending_tool_then_continues(monkeypatch):
    """도구 호출까지 저장하고 끊긴 transcript: 그 도구만 실행하고 이어서 모델을 부른다."""
    client, sent = _client(monkeypatch, [_msg("end_turn", Block(type="text", text="끝"))])
    saved = [{"role": "user", "content": "부산 코스"},
             {"role": "assistant", "content": [{"type": "tool_use", "id": "tu9", "name": "list_trips", "input": {}}]}]
    executed = []
    result = _run(client, saved, lambda n, r: executed.append(n) or '{"trips": []}', [])
    assert executed == ["list_trips"] and len(sent) == 1 and result.reply == "끝"


def test_tool_errors_are_flagged_and_limit_disables_tools(monkeypatch):
    client, sent = _client(monkeypatch, [
        _msg("tool_use", Block(type="tool_use", id="a", name="get_course", input={"trip_id": "x"})),
        _msg("end_turn", Block(type="text", text="코스를 찾지 못했어요.")),
    ])
    _run(client, [{"role": "user", "content": "코스"}], lambda n, r: json.dumps({"error": "없음"}), [], max_tool_calls=1)
    assert sent[1]["messages"][-1]["content"][0]["is_error"] is True
    assert sent[0]["allow_tools"] is True and sent[1]["allow_tools"] is False


def test_pause_turn_continues_and_refusal_raises(monkeypatch):
    client, sent = _client(monkeypatch, [
        _msg("pause_turn", Block(type="text", text="잠시만요")),
        _msg("end_turn", Block(type="text", text="완료")),
    ])
    result = _run(client, [{"role": "user", "content": "x"}], lambda n, r: "{}", [])
    assert len(sent) == 2 and result.reply == "잠시만요\n\n완료"
    client2, _ = _client(monkeypatch, [_msg("refusal")])
    with pytest.raises(AIRefusal):
        _run(client2, [{"role": "user", "content": "x"}], lambda n, r: "{}", [])
