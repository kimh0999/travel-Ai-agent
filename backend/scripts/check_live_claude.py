"""실제 Claude 연결 확인 (자동 테스트와 분리). ANTHROPIC_API_KEY가 필요하다. 모델은 CLAUDE_MODEL(기본 claude-opus-5-5).

실행: backend 폴더에서  .venv/Scripts/python scripts/check_live_claude.py
비용이 조금 발생한다(짧은 1일 코스 1회 생성 + 도구 1개를 쓰는 짧은 대화 1회).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.ai_base import ToolSpec  # noqa: E402
from app.clients.claude_client import ClaudeClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.schemas.chat import NoArgs  # noqa: E402
from app.schemas.course import CourseOut  # noqa: E402
from app.services.context_builder import (ContextMemory, CourseContext, build_course_prompt,  # noqa: E402
                                          load_prompt)


def main() -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("SKIP: ANTHROPIC_API_KEY가 없습니다.")
        return 2
    client = ClaudeClient(settings)

    # 1) 구조화 출력: 코스 생성
    ctx = CourseContext(
        trip={"id": "live-check", "destination": "부산", "days": 1, "days_is_default": True, "start_date": None,
              "end_date": None, "period_hint": None, "transport": "public", "companions": [], "budget": None,
              "conditions": None},
        home_base="서울",
        memories=[ContextMemory(id="pref_demo", strength="soft", subject="self", category="pace", scope="base",
                                value="하루 주요 방문지 두세 곳 선호", source_destinations=[])],
        unknown_categories=["budget"],
        past_trips=[],
    )
    started = time.monotonic()
    course = client.parse(kind="course", system=load_prompt("course_system.md"), user=build_course_prompt(ctx),
                          schema=CourseOut, context=ctx, timeout=settings.ai_timeout)
    print(f"OK course: model={client.model} effort={client.effort} elapsed={time.monotonic() - started:.1f}s")
    print(f"  title={course.title} days={len(course.days)} items_day1={len(course.days[0].items)}")
    print(f"  start_times={[i.start_time for i in course.days[0].items]}")

    # 2) 도구 호출 대화 턴 (DB 없이 도구 결과를 흉내 낸다)
    tools = [ToolSpec("list_trips", "사용자의 여행 목록을 조회한다.", NoArgs)]
    called = []

    def execute(name: str, raw: str) -> str:
        called.append(name)
        return json.dumps({"trips": []})

    started = time.monotonic()
    result = client.run_turn(
        system=load_prompt("chat_system.md") + "\n\n<session>\n오늘: 2026-09-30\n현재 작업 중인 여행: 없음\n</session>",
        transcript=[{"role": "user", "content": "내 여행 목록 알려줘"}], tools=tools, execute=execute,
        emit=lambda e: None, on_step=lambda m: None, deadline=time.monotonic() + 120, max_tool_calls=3)
    print(f"OK chat: elapsed={time.monotonic() - started:.1f}s tools={called}")
    print(f"  reply={result.reply[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
