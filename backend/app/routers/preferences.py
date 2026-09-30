from typing import Optional

from fastapi import APIRouter, Depends, Query, Response

from app.core.auth import AuthUser, current_user
from app.repositories import preferences as repo
from app.repositories import trips as trips_repo
from app.repositories import users as users_repo
from app.schemas.common import ONBOARDING_CATEGORIES, PreferenceStatus, Scope
from app.schemas.preferences import (Preference, PreferenceBrief, PreferenceCreate, PreferenceSummary,
                                     PreferenceUpdate)

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.post("", response_model=Preference, status_code=201)
def create_preference(body: PreferenceCreate, user: AuthUser = Depends(current_user)):
    if body.scope == "trip":
        trips_repo.get(user.uid, body.trip_id)  # 다른 사용자의 여행이면 404
    return repo.create(user.uid, body)


@router.get("", response_model=list[Preference])
def list_preferences(status: Optional[PreferenceStatus] = Query(default=None),
                     scope: Optional[Scope] = Query(default=None),
                     user: AuthUser = Depends(current_user)):
    if status == "deleted":
        return []  # 삭제된 기억은 조회 대상이 아니다.
    return repo.list_for_owner(user.uid, status=status, scope=scope)


@router.get("/summary", response_model=PreferenceSummary)
def preference_summary(user: AuthUser = Depends(current_user)):
    prefs = repo.list_for_owner(user.uid)
    by_category: dict[str, list[PreferenceBrief]] = {}
    for p in prefs:
        if p["status"] != "active" or p["scope"] == "trip":
            continue
        by_category.setdefault(p["category"], []).append(PreferenceBrief(**p))
    settings = users_repo.get_settings_doc(user.uid)
    return PreferenceSummary(
        home_base=settings.get("home_base"),
        by_category=by_category,
        unknown_categories=[c for c in ONBOARDING_CATEGORIES if c not in by_category],
        hard_count=sum(1 for items in by_category.values() for i in items if i.strength == "hard"),
        paused_count=sum(1 for p in prefs if p["status"] == "paused"),
    )


@router.get("/{pref_id}", response_model=Preference)
def get_preference(pref_id: str, user: AuthUser = Depends(current_user)):
    return repo.get(user.uid, pref_id)


@router.put("/{pref_id}", response_model=Preference)
def update_preference(pref_id: str, body: PreferenceUpdate, user: AuthUser = Depends(current_user)):
    return repo.update(user.uid, pref_id, body)


@router.delete("/{pref_id}", status_code=204)
def delete_preference(pref_id: str, user: AuthUser = Depends(current_user)):
    repo.soft_delete(user.uid, pref_id)
    return Response(status_code=204)
