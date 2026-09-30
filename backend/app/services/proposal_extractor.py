"""여행 피드백 → 기억 변경안(pending) 생성 (SPEC 8-4). 장기 기억은 여기서 절대 바꾸지 않는다."""
from typing import Any, Optional

from app.clients.factory import get_ai_client
from app.core.errors import AppError
from app.core.firebase import get_db
from app.repositories import feedback as feedback_repo
from app.repositories import preferences as prefs_repo
from app.repositories import proposals as proposals_repo
from app.repositories import trips as trips_repo
from app.schemas.common import utcnow
from app.schemas.proposals import ProposalDraft, ProposalExtraction
from app.services.ai_runner import call_structured
from app.services.context_builder import (FeedbackEntry, FeedbackVisit, ProposalContext, build_proposal_prompt,
                                          load_prompt, to_context_memory)
from app.services.memory_selector import is_ai_shareable


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").replace("<", "‹").replace(">", "›").split())


def _build_context(uid: str, trip: dict[str, Any], feedback: list[dict[str, Any]]):
    prefs = prefs_repo.list_for_owner(uid, status="active")
    trips_by_id = {t["id"]: t for t in trips_repo.list_for_owner(uid)}
    # 이번 여행 한정(scope=trip) 기억은 장기 기억 변경 대상이 아니므로 비교 대상에서도 뺀다.
    existing = [p for p in prefs if is_ai_shareable(p) and p["scope"] != "trip"]
    entries = [FeedbackEntry(
        feedback_id=f["id"], overall_text=f.get("overall_text") or "", overall_rating=f.get("overall_rating"),
        visits=[FeedbackVisit(item_id=v["item_id"], place_name=v["place_name"], visited=v["visited"],
                              rating=v.get("rating"), comment=v.get("comment") or "") for v in f.get("visits", [])],
    ) for f in feedback]
    ctx = ProposalContext(destination=trip["destination"], companions=trip.get("companions") or [],
                          feedback=entries, existing_memories=[to_context_memory(p, trips_by_id) for p in existing])
    return ctx, {p["id"]: p for p in existing}


def _locate_evidence(ctx: ProposalContext, draft: ProposalDraft) -> tuple[Optional[str], Optional[str]]:
    """근거 문장이 실제 피드백 원문(전체 소감 또는 '방문한' 장소 소감)에 있는지 찾는다.

    반환: (feedback_id, 폐기 사유). 폐기 사유가 있으면 제안을 버린다."""
    evidence = _norm(draft.evidence_text)
    found_in_unvisited = False
    for f in ctx.feedback:
        if evidence and evidence in _norm(f.overall_text):
            if draft.evidence_item_id:
                visit = next((v for v in f.visits if v.item_id == draft.evidence_item_id), None)
                if visit is not None and not visit.visited:
                    return None, f"방문하지 않은 장소({visit.place_name})에 대한 제안이라 제외했어요."
            return f.feedback_id, None
        for v in f.visits:
            if evidence and evidence in _norm(v.comment):
                if not v.visited:
                    found_in_unvisited = True
                    continue
                return f.feedback_id, None
    if found_in_unvisited:
        return None, "방문하지 않은 장소의 메모에서 나온 제안이라 제외했어요."
    return None, f"근거 문장('{draft.evidence_text[:40]}')을 피드백 원문에서 찾을 수 없어 제외했어요."


def generate_proposals(uid: str, trip_id: str) -> dict[str, Any]:
    trip = trips_repo.get(uid, trip_id)
    feedback = feedback_repo.list_for_trip(uid, trip_id)
    if not feedback:
        raise AppError(409, "NO_FEEDBACK", "먼저 여행 피드백을 남겨 주세요.")
    ctx, existing_by_id = _build_context(uid, trip, feedback)
    extraction: ProposalExtraction = call_structured(
        "proposals", load_prompt("proposal_system.md"), build_proposal_prompt(ctx), ProposalExtraction, ctx)

    client = get_ai_client()
    discarded: list[str] = []
    accepted: list[tuple[ProposalDraft, str]] = []
    existing_values = {(p["category"], p["value"].strip()) for p in existing_by_id.values()}
    for draft in extraction.proposals:
        feedback_id, reason = _locate_evidence(ctx, draft)
        if reason:
            discarded.append(reason)
            continue
        if draft.type in ("update", "deactivate") and draft.target_preference_id not in existing_by_id:
            discarded.append(f"존재하지 않는 기억을 바꾸려는 제안이라 제외했어요 ('{(draft.after or '')[:30]}').")
            continue
        if draft.type == "add" and (draft.category, (draft.after or "").strip()) in existing_values:
            discarded.append(f"이미 저장된 기억과 같아 제외했어요 ('{draft.after}').")
            continue
        if draft.type == "update" and draft.target_preference_id:
            draft.before = existing_by_id[draft.target_preference_id]["value"]  # 변경 전 값은 서버 기준으로 표시
        if draft.type == "deactivate" and draft.target_preference_id:
            draft.before = existing_by_id[draft.target_preference_id]["value"]
            draft.after = None
        accepted.append((draft, feedback_id))

    # 같은 여행의 미결정 변경안은 새 결과로 교체한다(승인·거절된 기록은 유지).
    proposals_repo.delete_pending(uid, trip_id)
    now = utcnow()
    batch = get_db().batch()
    saved = []
    for draft, feedback_id in accepted:
        ref = proposals_repo.col().document()
        data = {**draft.model_dump(), "owner_uid": uid, "trip_id": trip_id, "feedback_id": feedback_id,
                "status": "pending", "edited_value": None, "result_preference_id": None, "is_mock": client.is_mock,
                "created_at": now, "decided_at": None}
        batch.set(ref, data)
        saved.append({**data, "id": ref.id})
    if saved:
        batch.commit()
    return {"proposals": saved, "excluded_notes": extraction.excluded_notes, "discarded": discarded}
