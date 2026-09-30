from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, current_user
from app.repositories import users as repo
from app.schemas.users import UserSettings, UserSettingsUpdate

router = APIRouter(prefix="/api/me", tags=["me"])


def _out(user: AuthUser, data: dict) -> UserSettings:
    return UserSettings(uid=user.uid, email=user.email, home_base=data.get("home_base"),
                        onboarded=bool(data.get("onboarded")), default_trip_days=int(data.get("default_trip_days", 3)))


@router.get("", response_model=UserSettings)
def get_me(user: AuthUser = Depends(current_user)):
    return _out(user, repo.get_settings_doc(user.uid))


@router.put("", response_model=UserSettings)
def update_me(body: UserSettingsUpdate, user: AuthUser = Depends(current_user)):
    return _out(user, repo.update_settings(user.uid, body))
