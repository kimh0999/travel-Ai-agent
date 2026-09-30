"""여행 삭제 정책 (SPEC 6-3).

함께 삭제: 대화 속 이 여행의 카드와 실행 기록, 피드백, 승인되지 않은 변경안(대기·거절), scope=trip 기억, 코스 버전.
대화 자체는 여러 여행을 다룰 수 있으므로 지우지 않고, 이 여행을 작업 중이던 대화는 여행 연결만 푼다.
유지: 이미 승인된 learned 기억과 승인된 변경안 기록 — 단, 출처에 '삭제된 여행' 표시(trip_deleted=true).
사용자가 삭제 확인 화면에서 고른 learned 기억은 함께 삭제(소프트 삭제 → 30일 후 정리)한다.
각 단계는 다시 실행해도 안전하며, 여행 문서는 마지막에 지운다(중간 실패 시 재시도 가능).
"""
from typing import Any

from google.cloud.firestore import FieldFilter

from app.core.errors import AppError
from app.core.firebase import get_db
from app.repositories import conversations as conv_repo
from app.repositories import feedback as feedback_repo
from app.repositories import preferences as prefs_repo
from app.repositories import proposals as proposals_repo
from app.repositories import trips as trips_repo
from app.repositories import turns as turns_repo
from app.repositories import versions as versions_repo
from app.repositories.base import delete_query_in_batches, snap_to_dict
from app.schemas.common import utcnow


def _refers_to(pref: dict[str, Any], trip_id: str) -> bool:
    return any(s.get("trip_id") == trip_id for s in pref.get("sources", []))


def _learned_from_trip(uid: str, trip_id: str) -> list[dict[str, Any]]:
    return [p for p in prefs_repo.list_for_owner(uid) if p["scope"] == "learned" and _refers_to(p, trip_id)]


def _owned_where(collection: str, uid: str, trip_id: str) -> list[dict[str, Any]]:
    col = get_db().collection(collection)
    docs = [snap_to_dict(s) for s in col.where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    return [d for d in docs if d.get("trip_id") == trip_id]


def preview(uid: str, trip_id: str) -> dict[str, Any]:
    trip = trips_repo.get(uid, trip_id)
    learned = _learned_from_trip(uid, trip_id)
    proposals = proposals_repo.list_for_owner(uid, trip_id=trip_id)
    return {
        "trip_id": trip_id,
        "destination": trip["destination"],
        "learned_preferences": [{
            "id": p["id"], "value": p["value"], "category": p["category"],
            "only_from_this_trip": all(s.get("trip_id") == trip_id for s in p.get("sources", [])),
        } for p in learned],
        "counts": {
            "conversations": sum(1 for c in conv_repo.list_for_owner(uid) if c.get("trip_id") == trip_id),
            "feedback": len(_owned_where("feedback", uid, trip_id)),
            "undecided_proposals": sum(1 for p in proposals if p["status"] in ("pending", "rejected")),
            "trip_preferences": len(prefs_repo.list_for_owner(uid, scope="trip", trip_id=trip_id, include_deleted=True)),
            "course_versions": len(versions_repo.list_for_trip(uid, trip_id)),
        },
    }


def delete_trip(uid: str, trip_id: str, delete_preference_ids: list[str]) -> dict[str, Any]:
    trips_repo.get(uid, trip_id)
    db = get_db()
    learned_ids = {p["id"] for p in _learned_from_trip(uid, trip_id)}
    requested = set(delete_preference_ids)
    invalid = requested - learned_ids
    if invalid:
        raise AppError(422, "VALIDATION_ERROR", "이 여행에서 비롯된 기억만 함께 삭제할 수 있습니다.")

    now = utcnow()
    # 1) 출처 표시·선택한 learned 기억 삭제 (이 여행을 출처로 가진 모든 기억)
    for pref in prefs_repo.list_for_owner(uid, include_deleted=True):
        if pref["scope"] == "trip" or not _refers_to(pref, trip_id):
            continue
        sources = [{**s, "trip_deleted": True} if s.get("trip_id") == trip_id else s
                   for s in pref.get("sources", [])]
        changes: dict[str, Any] = {"sources": sources, "updated_at": now}
        if pref["id"] in requested and pref["status"] != "deleted":
            changes.update({"status": "deleted", "deleted_at": now})
        prefs_repo.ref(pref["id"]).update(changes)

    # 2) 대화 속 이 여행의 카드·실행 기록 (대화는 남기고 여행 연결만 푼다)
    conversations = conv_repo.strip_trip(uid, trip_id)
    turns_repo.delete_mentioning(uid, trip_id)
    # 3) 피드백
    feedback = feedback_repo.list_for_trip(uid, trip_id)
    for f in feedback:
        feedback_repo.delete(uid, f["id"])
    # 4) 승인되지 않은 변경안(대기·거절). 승인된 변경안은 learned 기억의 근거 기록으로 남긴다.
    undecided = [p for p in proposals_repo.list_for_owner(uid, trip_id=trip_id) if p["status"] in ("pending", "rejected")]
    for p in undecided:
        proposals_repo.col().document(p["id"]).delete()
    # 5) 이 여행 한정(scope=trip) 기억
    trip_prefs = prefs_repo.list_for_owner(uid, scope="trip", trip_id=trip_id, include_deleted=True)
    for p in trip_prefs:
        prefs_repo.ref(p["id"]).delete()
    # 6) 코스 버전
    versions_deleted = delete_query_in_batches(db, versions_repo.collection(trip_id))
    # 7) 여행
    trips_repo.ref(trip_id).delete()

    return {
        "deleted": {"conversations": conversations, "feedback": len(feedback), "undecided_proposals": len(undecided),
                    "trip_preferences": len(trip_prefs), "course_versions": versions_deleted,
                    "learned_preferences": len(requested)},
        "kept_learned_preference_ids": sorted(learned_ids - requested),
        "deleted_preference_ids": sorted(requested),
    }
