from typing import Any, Optional

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore import FieldFilter

from app.core.firebase import get_db
from app.repositories.base import delete_query_in_batches, get_owned, get_owned_snapshot, snap_to_dict
from app.schemas.common import utcnow

COLLECTION = "conversations"


def col():
    return get_db().collection(COLLECTION)


def create(uid: str, title: str, trip_id: Optional[str], doc_id: Optional[str] = None) -> dict[str, Any]:
    """doc_id를 주면 그 ID로 한 번만 만든다(이미 있으면 기존 대화를 돌려준다)."""
    now = utcnow()
    data = {"owner_uid": uid, "title": title, "trip_id": trip_id, "summary": None, "message_count": 0,
            "last_message_at": None, "created_at": now, "updated_at": now}
    if doc_id is None:
        ref = col().document()
        ref.set(data)
        return {**data, "id": ref.id}
    try:
        col().document(doc_id).create(data)
    except AlreadyExists:
        return get(uid, doc_id)
    return {**data, "id": doc_id}


def list_for_owner(uid: str) -> list[dict[str, Any]]:
    docs = [snap_to_dict(s) for s in col().where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    docs.sort(key=lambda d: d.get("last_message_at") or d["created_at"], reverse=True)
    return docs


def get(uid: str, conversation_id: str) -> dict[str, Any]:
    return get_owned(col().document(conversation_id), uid, "대화")


def set_trip(conversation_id: str, trip_id: Optional[str]) -> None:
    """대화의 '현재 작업 중인 여행'을 바꾼다. 대화 기록과 여행 데이터는 따로 관리한다."""
    col().document(conversation_id).update({"trip_id": trip_id, "updated_at": utcnow()})


def messages(uid: str, conversation_id: str) -> list[dict[str, Any]]:
    docs = [snap_to_dict(s) for s in col().document(conversation_id).collection("messages").stream()]
    docs = [d for d in docs if d.get("owner_uid") == uid]
    docs.sort(key=lambda d: d["seq"])
    return docs


def append_turn(uid: str, conversation_id: str, turn_id: str, user_text: str, reply: str,
                cards: list[dict[str, Any]]) -> None:
    """한 턴의 질문·답변·카드를 한 트랜잭션으로 저장한다. 같은 턴을 다시 저장해도 한 번만 들어간다."""
    db = get_db()
    ref = col().document(conversation_id)
    msgs = ref.collection("messages")
    user_ref, reply_ref = msgs.document(f"{turn_id}-1"), msgs.document(f"{turn_id}-2")

    @firestore.transactional
    def txn_fn(txn):
        snap = get_owned_snapshot(ref, uid, "대화", transaction=txn)
        if user_ref.get(transaction=txn).exists:
            return
        seq = int(snap.to_dict().get("message_count", 0))
        now = utcnow()
        txn.set(user_ref, {"owner_uid": uid, "role": "user", "content": user_text, "cards": [], "turn_id": turn_id,
                           "seq": seq + 1, "created_at": now})
        txn.set(reply_ref, {"owner_uid": uid, "role": "assistant", "content": reply, "cards": cards,
                            "turn_id": turn_id, "seq": seq + 2, "created_at": now})
        txn.update(ref, {"message_count": seq + 2, "last_message_at": now, "updated_at": now,
                         "summary": " ".join(reply.split())[:120]})

    txn_fn(db.transaction())


def _card_trip_id(card: dict[str, Any]) -> Optional[str]:
    if card.get("trip"):
        return card["trip"].get("id")
    return (card.get("proposal") or {}).get("trip_id")


def strip_trip(uid: str, trip_id: str) -> int:
    """삭제한 여행의 카드를 대화에서 지우고, 그 여행을 작업 중인 대화는 여행 연결만 푼다. 바뀐 대화 수를 반환."""
    touched = 0
    for conv in list_for_owner(uid):
        changed = conv.get("trip_id") == trip_id
        if changed:
            set_trip(conv["id"], None)
        for m in messages(uid, conv["id"]):
            cards = m.get("cards") or []
            kept = [c for c in cards if _card_trip_id(c) != trip_id]
            if len(kept) != len(cards):
                col().document(conv["id"]).collection("messages").document(m["id"]).update({"cards": kept})
                changed = True
        touched += int(changed)
    return touched


def delete(conversation_id: str) -> None:
    db = get_db()
    ref = col().document(conversation_id)
    delete_query_in_batches(db, ref.collection("messages"))
    ref.delete()
