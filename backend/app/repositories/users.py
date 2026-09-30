from typing import Any

from app.core.firebase import get_db
from app.schemas.common import utcnow
from app.schemas.users import UserSettingsUpdate

DEFAULTS = {"home_base": None, "onboarded": False, "default_trip_days": 3}


def get_settings_doc(uid: str) -> dict[str, Any]:
    # users 문서 ID는 검증된 uid 자체이므로 다른 사용자의 문서에 접근할 경로가 없다.
    snap = get_db().collection("users").document(uid).get()
    data = {**DEFAULTS, **(snap.to_dict() or {})} if snap.exists else dict(DEFAULTS)
    return data


def update_settings(uid: str, body: UserSettingsUpdate) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if "home_base" in changes and changes["home_base"] is not None:
        changes["home_base"] = changes["home_base"].strip() or None
    changes = {k: v for k, v in changes.items() if v is not None or k == "home_base"}
    now = utcnow()
    ref = get_db().collection("users").document(uid)
    if not ref.get().exists:
        ref.set({**DEFAULTS, "owner_uid": uid, "created_at": now, "updated_at": now})
    if changes:
        ref.update({**changes, "updated_at": now})
    return get_settings_doc(uid)
