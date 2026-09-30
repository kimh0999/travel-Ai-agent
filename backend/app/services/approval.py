"""기억 변경안 승인·거절 (SPEC 4-4 멱등성).

- Firestore 트랜잭션 안에서 '제안 상태 확인'과 '기억 생성·수정'을 함께 처리한다.
- add 승인으로 만드는 기억의 문서 ID는 proposal_id에서 결정적으로 파생한다(prop_{proposal_id}).
  → 동시에 두 번 승인해도 같은 문서 하나만 생긴다.
- 사용자 승인 API에서만 호출된다. AI 도구에는 이 기능이 노출되지 않는다.
"""
from typing import Any, Optional

from google.cloud import firestore
from google.cloud.firestore import ArrayUnion

from app.core.errors import AppError
from app.core.firebase import get_db
from app.repositories import preferences as prefs_repo
from app.repositories import proposals as proposals_repo
from app.repositories import trips as trips_repo
from app.repositories.base import get_owned_snapshot
from app.schemas.common import utcnow

APPROVED = ("approved", "edited_approved")
MAX_ATTEMPTS = 10


def learned_preference_id(proposal_id: str) -> str:
    return f"prop_{proposal_id}"


def _source(p: dict[str, Any], proposal_id: str, destination: Optional[str]) -> dict[str, Any]:
    return {"type": "feedback_proposal", "trip_id": p.get("trip_id"), "feedback_id": p.get("feedback_id"),
            "proposal_id": proposal_id, "evidence_text": p["evidence_text"], "trip_deleted": False,
            "trip_destination": destination}


def approve(uid: str, proposal_id: str, edited_value: Optional[str]) -> dict[str, Any]:
    db = get_db()
    proposal_ref = proposals_repo.col().document(proposal_id)
    edited = edited_value.strip() if edited_value else None

    @firestore.transactional
    def txn_fn(txn) -> dict[str, Any]:
        # 트랜잭션 규칙: 모든 읽기를 쓰기보다 먼저 한다.
        snap = get_owned_snapshot(proposal_ref, uid, "변경안", transaction=txn)
        p = snap.to_dict()
        if p["status"] in APPROVED:
            return {"proposal": {**p, "id": proposal_id}, "preference_id": p.get("result_preference_id"),
                    "already_decided": True}
        if p["status"] == "rejected":
            raise AppError(409, "CONFLICT", "이미 거절한 변경안입니다.")
        if edited and p["type"] == "deactivate":
            raise AppError(422, "VALIDATION_ERROR", "비활성화 제안은 값을 수정해 승인할 수 없습니다.")

        destination = None
        if p.get("trip_id"):
            trip_snap = trips_repo.ref(p["trip_id"]).get(transaction=txn)
            destination = (trip_snap.to_dict() or {}).get("destination") if trip_snap.exists else None
        target_ref = None
        if p["type"] in ("update", "deactivate"):
            target_ref = prefs_repo.ref(p["target_preference_id"])
            target = target_ref.get(transaction=txn)
            tdata = target.to_dict() or {}
            if not target.exists or tdata.get("owner_uid") != uid or tdata.get("status") == "deleted":
                raise AppError(409, "CONFLICT", "변경하려는 기억이 삭제되었거나 존재하지 않습니다.")
        else:
            target_ref = prefs_repo.ref(learned_preference_id(proposal_id))
            existing = target_ref.get(transaction=txn)

        now = utcnow()
        value = edited or p.get("after")
        source = _source(p, proposal_id, destination)
        if p["type"] == "add":
            if not existing.exists:
                txn.create(target_ref, {
                    "owner_uid": uid, "scope": "learned", "trip_id": None, "strength": p["strength"],
                    "subject": p["subject"], "category": p["category"], "value": value, "status": "active",
                    "sources": [source], "sensitive": False, "share_with_ai": True,
                    "created_at": now, "updated_at": now, "deleted_at": None,
                })
        elif p["type"] == "update":
            txn.update(target_ref, {"value": value, "updated_at": now, "sources": ArrayUnion([source])})
        else:  # deactivate → 잠시 적용하지 않음(paused). 사용자가 '내 취향'에서 다시 켤 수 있다.
            txn.update(target_ref, {"status": "paused", "updated_at": now, "sources": ArrayUnion([source])})

        status = "edited_approved" if edited and edited != p.get("after") else "approved"
        changes = {"status": status, "edited_value": edited if status == "edited_approved" else None,
                   "decided_at": now, "result_preference_id": target_ref.id}
        txn.update(proposal_ref, changes)
        return {"proposal": {**p, **changes, "id": proposal_id}, "preference_id": target_ref.id,
                "already_decided": False}

    try:
        return txn_fn(db.transaction(max_attempts=MAX_ATTEMPTS))
    except ValueError:
        # 동시 승인 경합으로 커밋에 실패한 경우: 다른 요청이 이미 승인했다면 같은 결과를 돌려준다(멱등).
        current = proposals_repo.get(uid, proposal_id)
        if current["status"] in APPROVED:
            return {"proposal": current, "preference_id": current.get("result_preference_id"), "already_decided": True}
        raise AppError(409, "CONFLICT", "다른 요청과 동시에 처리되어 승인하지 못했습니다. 다시 시도해 주세요.")


def reject(uid: str, proposal_id: str) -> dict[str, Any]:
    db = get_db()
    proposal_ref = proposals_repo.col().document(proposal_id)

    @firestore.transactional
    def txn_fn(txn) -> dict[str, Any]:
        p = get_owned_snapshot(proposal_ref, uid, "변경안", transaction=txn).to_dict()
        if p["status"] == "rejected":
            return {**p, "id": proposal_id}
        if p["status"] in APPROVED:
            raise AppError(409, "CONFLICT", "이미 승인한 변경안입니다. 기억 수정·삭제는 '내 취향'에서 하세요.")
        changes = {"status": "rejected", "decided_at": utcnow()}
        txn.update(proposal_ref, changes)
        return {**p, **changes, "id": proposal_id}

    return txn_fn(db.transaction())
