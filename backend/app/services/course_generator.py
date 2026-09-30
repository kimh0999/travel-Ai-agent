"""코스 생성 고정 파이프라인 (SPEC 8-1). 도구 호출 에이전트가 아니다.

1 인증(라우터) → 2 활성 취향·필수 제약 → 3 이번 여행 조건 → 4 과거 여행의 승인된 기억
→ 5 장소 후보 검색 → 6 컨텍스트 구성 → 7 AI 호출 → 8 Pydantic 검증(실패 시 1회 재시도)
→ 9 코스 버전 저장 → 10 반환
AI 호출이 실패하면 아무것도 저장하지 않으므로 기존 코스와 여행 입력은 그대로 남는다.
"""
import time
from typing import Any, Optional

from app.clients.factory import get_ai_client, get_place_provider
from app.core.errors import AppError
from app.repositories import preferences as prefs_repo
from app.repositories import trips as trips_repo
from app.repositories import users as users_repo
from app.repositories import versions as versions_repo
from app.schemas.common import ONBOARDING_CATEGORIES, utcnow
from app.schemas.course import CourseOut, StoredCourse
from app.services.ai_runner import call_structured
from app.services.context_builder import (CourseContext, PastTrip, build_course_prompt, load_prompt,
                                          to_context_memory)
from app.services.course_validator import validate_schedule
from app.services.memory_selector import Selection, is_ai_shareable, select_for_trip
from app.services.place_verifier import search_candidates, verify_course

ACTIVITY_KEYWORDS = ["자연", "카페", "음식", "문화", "쇼핑", "액티비티", "휴양", "바다", "시장", "야경"]


def _past_trips(uid: str, trip_id: str, prefs: list[dict[str, Any]], trips: list[dict[str, Any]]) -> list[PastTrip]:
    """과거 여행에서 사용자가 승인한 기억(learned, active, AI 전송 가능)만 교훈으로 쓴다. 미승인 피드백 원문은 넣지 않는다."""
    by_trip: dict[str, list[str]] = {}
    for p in prefs:
        if p["status"] != "active" or not is_ai_shareable(p) or p["scope"] == "trip":
            continue
        for s in p.get("sources", []):
            tid = s.get("trip_id")
            if s.get("type") == "feedback_proposal" and tid and tid != trip_id and not s.get("trip_deleted"):
                by_trip.setdefault(tid, []).append(p["value"])
    trips_by_id = {t["id"]: t for t in trips}
    return [PastTrip(trip_id=tid, destination=trips_by_id[tid]["destination"], lessons=lessons)
            for tid, lessons in by_trip.items() if tid in trips_by_id]


def build_course_context(uid: str, trip: dict[str, Any]) -> tuple[CourseContext, Selection]:
    prefs = prefs_repo.list_for_owner(uid)
    trips = trips_repo.list_for_owner(uid)
    trips_by_id = {t["id"]: t for t in trips}
    selection = select_for_trip(prefs, trip)
    memories = [to_context_memory(p, trips_by_id) for p in selection.selected]
    known = {p["category"] for p in selection.selected} | {p["category"] for p in selection.withheld_sensitive}
    settings_doc = users_repo.get_settings_doc(uid)
    ctx = CourseContext(
        trip={k: trip.get(k) for k in ("id", "destination", "days", "days_is_default", "start_date", "end_date",
                                        "period_hint", "transport", "companions", "budget", "conditions")},
        home_base=settings_doc.get("home_base"),
        memories=memories,
        unknown_categories=[c for c in ONBOARDING_CATEGORIES if c not in known],
        past_trips=_past_trips(uid, trip["id"], prefs, trips),
        pinned=[p["name"] for p in trip.get("pinned_places") or []],
    )
    return ctx, selection


def _candidate_keywords(ctx: CourseContext) -> list[str]:
    text = " ".join(m.value for m in ctx.memories if m.category in ("activity", "food")) + " " + (ctx.request_note or "")
    keywords = [k for k in ACTIVITY_KEYWORDS if k in text]
    return keywords + ["관광명소"] if "관광명소" not in keywords else keywords


def enrich_applied(course: CourseOut, allowed: dict[str, dict[str, Any]], trips_by_id: dict[str, dict[str, Any]]):
    """AI가 적은 적용 기억 중 실제로 제공한 기억만 남기고 화면 표시용 정보를 붙인다."""
    out, seen = [], set()
    item_ids = [pid for d in course.days for i in d.items for pid in i.applied_preference_ids]
    entries = [(a.preference_id, a.reason) for a in course.applied_memories] + [(pid, "코스 항목 구성에 반영했어요.") for pid in item_ids]
    for pid, reason in entries:
        pref = allowed.get(pid)
        if not pref or pid in seen:
            continue
        seen.add(pid)
        mem = to_context_memory(pref, trips_by_id)
        out.append({"preference_id": pid, "reason": reason, "value": pref["value"], "category": pref["category"],
                    "scope": pref["scope"], "strength": pref["strength"], "subject": pref["subject"],
                    "source_destinations": mem.source_destinations})
    return out


def _strip_unknown_ids(course: CourseOut, allowed_ids: set[str]) -> CourseOut:
    data = course.model_dump()
    data["applied_memories"] = [a for a in data["applied_memories"] if a["preference_id"] in allowed_ids]
    for day in data["days"]:
        for item in day["items"]:
            item["applied_preference_ids"] = [p for p in item["applied_preference_ids"] if p in allowed_ids]
    return CourseOut.model_validate(data)


def _norm_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _find_pin(course: CourseOut, pin: dict[str, str]) -> Optional[str]:
    """고정 장소에 해당하는 항목의 item_id. 같은 item_id가 같은 이름이면 그것, 아니면 이름으로 찾는다."""
    target = _norm_name(pin["name"])
    items = [i for d in course.days for i in d.items]
    for i in items:
        if i.item_id == pin["item_id"] and _norm_name(i.name) == target:
            return i.item_id
    for i in items:
        cand = _norm_name(i.name)
        if cand and target and (cand == target or target in cand or cand in target):
            return i.item_id
    return None


def match_pins(course: CourseOut, pinned: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    """(새 코스 기준으로 item_id를 갱신한 고정 목록, 코스에서 빠진 고정 장소 이름)."""
    kept, missing = [], []
    for pin in pinned:
        item_id = _find_pin(course, pin)
        if item_id:
            kept.append({"item_id": item_id, "name": pin["name"]})
        else:
            missing.append(pin["name"])
    return kept, missing


def _mark_pins(stored: StoredCourse, pinned: list[dict[str, str]]) -> dict[str, Any]:
    data = stored.model_dump(mode="json")
    ids = {p["item_id"] for p in pinned}
    for day in data["days"]:
        for item in day["items"]:
            item["pinned"] = item["item_id"] in ids
    return data


def _existing(uid: str, trip_id: str, version_id: str) -> Optional[dict[str, Any]]:
    try:
        return versions_repo.get(uid, trip_id, version_id)
    except AppError:
        return None


def generate_course(uid: str, trip_id: str, request_note: Optional[str] = None,
                    version_id: Optional[str] = None) -> dict[str, Any]:
    """version_id를 주면 그 ID로 한 번만 저장한다(재시도 중복 방지). 이미 있으면 AI를 다시 부르지 않는다."""
    started = time.monotonic()
    trip = trips_repo.get(uid, trip_id)
    if version_id:
        done = _existing(uid, trip_id, version_id)
        if done:
            return done
    ctx, selection = build_course_context(uid, trip)
    ctx.request_note = request_note
    provider = get_place_provider()
    ctx.place_candidates = search_candidates(provider, trip["destination"], _candidate_keywords(ctx))
    prompt = build_course_prompt(ctx)
    client = get_ai_client()
    system = load_prompt("course_system.md")
    course: CourseOut = call_structured("course", system, prompt, CourseOut, ctx, started)
    trip_pins = trip.get("pinned_places") or []
    pinned, missing = match_pins(course, trip_pins)
    if missing:  # 고정 장소가 빠졌으면 한 번 더 요청한다.
        retry_prompt = prompt + f"\n\n주의: 고정 장소({', '.join(missing)})가 빠졌습니다. 반드시 포함해 다시 만들어 주세요."
        course = call_structured("course", system, retry_prompt, CourseOut, ctx, started)
        pinned, missing = match_pins(course, trip_pins)

    allowed = {p["id"]: p for p in selection.selected}
    course = _strip_unknown_ids(course, set(allowed))
    stored: StoredCourse = verify_course(provider, trip["destination"], course)
    warnings = validate_schedule(course, trip["days"])
    warnings += [f"고정한 장소 '{name}'을(를) 코스에 넣지 못했어요." for name in missing]
    trips_by_id = {t["id"]: t for t in trips_repo.list_for_owner(uid)}
    existing = versions_repo.list_for_trip(uid, trip_id)
    version = versions_repo.create(uid, trip_id, {
        "kind": "original",
        "parent_version_id": None,
        "label": f"AI 생성 {sum(1 for v in existing if v['kind'] == 'original') + 1}",
        "course": _mark_pins(stored, pinned),
        "applied_memories": enrich_applied(course, allowed, trips_by_id),
        "generation_basis": {
            "memory_ids": [m.id for m in ctx.memories],
            "withheld_sensitive_ids": [p["id"] for p in selection.withheld_sensitive],
            "unknown_categories": ctx.unknown_categories,
            "past_trip_ids": [p.trip_id for p in ctx.past_trips],
            "place_candidates": len(ctx.place_candidates),
            "model": client.model,
            "is_mock": client.is_mock,
            "place_provider": provider.name,
            "generated_at": utcnow(),
        },
        "warnings": warnings,
        "changes": [],
        "changed_days": [],
    }, doc_id=version_id)
    trips_repo.set_current_version(trip_id, version["id"])
    # 코스에서 찾은 고정 장소는 새 item_id로 갱신하고, 못 넣은 고정 장소도 목록에서 지우지 않는다.
    trips_repo.set_pinned(trip_id, pinned + [p for p in trip_pins if p["name"] in missing])
    return version


def save_revision(uid: str, trip_id: str, parent_version_id: str, course: CourseOut, label: Optional[str],
                  source: str = "user", changes: Optional[list[str]] = None, changed_days: Optional[list[int]] = None,
                  version_id: Optional[str] = None) -> dict[str, Any]:
    """수정본을 새 버전으로 저장한다. 고정한 장소가 빠지면 저장하지 않는다(422).

    version_id를 주면 그 ID로 한 번만 저장한다(재시도 중복 방지)."""
    trip = trips_repo.get(uid, trip_id)
    if version_id:
        done = _existing(uid, trip_id, version_id)
        if done:
            return done
    versions_repo.get(uid, trip_id, parent_version_id)
    pinned, missing = match_pins(course, trip.get("pinned_places") or [])
    if missing:
        raise AppError(422, "PINNED_REMOVED",
                       f"고정한 장소({', '.join(missing)})는 빼면 안 됩니다. 고정한 장소를 유지한 채 다시 수정하세요.")
    prefs = {p["id"]: p for p in prefs_repo.list_for_owner(uid) if p["status"] == "active"}
    course = _strip_unknown_ids(course, set(prefs))
    provider = get_place_provider()
    stored = verify_course(provider, trip["destination"], course)
    warnings = validate_schedule(course, trip["days"])
    trips_by_id = {t["id"]: t for t in trips_repo.list_for_owner(uid)}
    existing = versions_repo.list_for_trip(uid, trip_id)
    version = versions_repo.create(uid, trip_id, {
        "kind": "revision",
        "parent_version_id": parent_version_id,
        "label": (label or f"수정본 {sum(1 for v in existing if v['kind'] == 'revision') + 1}")
                 + (" (AI 대화)" if source == "chat" else ""),
        "course": _mark_pins(stored, pinned),
        "applied_memories": enrich_applied(course, prefs, trips_by_id),
        "generation_basis": None,
        "warnings": warnings,
        "changes": changes or [],
        "changed_days": changed_days or [],
    }, doc_id=version_id)
    trips_repo.set_current_version(trip_id, version["id"])
    trips_repo.set_pinned(trip_id, pinned)
    return version


MAX_PINS = 10


def set_pin(uid: str, trip_id: str, item_id: str, pinned: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """현재 코스의 장소를 고정하거나 고정을 푼다. (갱신된 여행, 대상 항목)"""
    trip = trips_repo.get(uid, trip_id)
    if not trip.get("current_version_id"):
        raise AppError(409, "NO_COURSE", "아직 코스가 없어 장소를 고정할 수 없습니다.")
    version = versions_repo.get(uid, trip_id, trip["current_version_id"])
    item = next((i for d in version["course"]["days"] for i in d["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise AppError(404, "NOT_FOUND", "현재 코스에서 그 장소를 찾을 수 없습니다.")
    if item["kind"] == "rest":
        raise AppError(422, "VALIDATION_ERROR", "휴식 구간은 고정할 수 없어요.")
    target = _norm_name(item["name"])
    pins = [p for p in trip.get("pinned_places") or [] if p["item_id"] != item_id and _norm_name(p["name"]) != target]
    if pinned:
        if len(pins) >= MAX_PINS:
            raise AppError(422, "VALIDATION_ERROR", f"장소는 최대 {MAX_PINS}곳까지 고정할 수 있어요.")
        pins.append({"item_id": item_id, "name": item["name"]})
    trips_repo.set_pinned(trip_id, pins)
    return {**trip, "pinned_places": pins}, item


def restore_version(uid: str, trip_id: str, version_id: str) -> dict[str, Any]:
    """이전 버전을 다시 현재 코스로 지정한다. 버전은 지우지 않으므로 언제든 다시 바꿀 수 있다."""
    trip = trips_repo.get(uid, trip_id)
    versions_repo.get(uid, trip_id, version_id)
    trips_repo.set_current_version(trip_id, version_id)
    return {**trip, "current_version_id": version_id}
