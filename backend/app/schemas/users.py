from typing import Optional

from pydantic import BaseModel, Field


class UserSettings(BaseModel):
    uid: str
    email: Optional[str]
    home_base: Optional[str]
    onboarded: bool
    default_trip_days: int


class UserSettingsUpdate(BaseModel):
    home_base: Optional[str] = Field(default=None, max_length=100)
    onboarded: Optional[bool] = None
    default_trip_days: Optional[int] = Field(default=None, ge=1, le=14)
