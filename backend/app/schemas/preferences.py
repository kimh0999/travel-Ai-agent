from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Category, PreferenceStatus, Scope, Strength, Subject

SourceType = Literal["manual", "onboarding", "feedback_proposal", "chat"]  # chat: 대화에서 말한 이번 여행 조건


class PreferenceSource(BaseModel):
    type: SourceType
    trip_id: Optional[str] = None
    feedback_id: Optional[str] = None
    proposal_id: Optional[str] = None
    evidence_text: Optional[str] = None
    trip_deleted: bool = False
    trip_destination: Optional[str] = None


class PreferenceCreate(BaseModel):
    scope: Literal["base", "trip"] = "base"  # learned는 승인 API로만 생성된다.
    trip_id: Optional[str] = Field(default=None, max_length=64)
    strength: Strength = "soft"
    subject: Subject = "self"
    category: Category
    value: str = Field(min_length=1, max_length=200)
    sensitive: bool = False
    share_with_ai: Optional[bool] = None  # 미지정 시 sensitive면 False, 아니면 True
    source_type: Literal["manual", "onboarding"] = "manual"

    @model_validator(mode="after")
    def _check_scope(self):
        self.value = self.value.strip()
        if not self.value:
            raise ValueError("value는 비어 있을 수 없습니다.")
        if self.scope == "trip" and not self.trip_id:
            raise ValueError("scope=trip이면 trip_id가 필요합니다.")
        if self.scope == "base" and self.trip_id:
            raise ValueError("scope=base에는 trip_id를 지정할 수 없습니다.")
        if self.share_with_ai is None:
            self.share_with_ai = not self.sensitive
        return self


class PreferenceUpdate(BaseModel):
    value: Optional[str] = Field(default=None, min_length=1, max_length=200)
    strength: Optional[Strength] = None
    subject: Optional[Subject] = None
    category: Optional[Category] = None
    status: Optional[Literal["active", "paused"]] = None  # 삭제는 DELETE로만
    sensitive: Optional[bool] = None
    share_with_ai: Optional[bool] = None

    @model_validator(mode="after")
    def _strip(self):
        if self.value is not None:
            self.value = self.value.strip()
            if not self.value:
                raise ValueError("value는 비어 있을 수 없습니다.")
        return self


class Preference(BaseModel):
    id: str
    owner_uid: str
    scope: Scope
    trip_id: Optional[str] = None
    strength: Strength
    subject: Subject
    category: Category
    value: str
    status: PreferenceStatus
    sources: list[PreferenceSource]
    sensitive: bool
    share_with_ai: bool
    created_at: datetime
    updated_at: datetime


class PreferenceBrief(BaseModel):
    id: str
    value: str
    strength: Strength
    subject: Subject
    scope: Scope


class PreferenceSummary(BaseModel):
    home_base: Optional[str]
    by_category: dict[str, list[PreferenceBrief]]
    unknown_categories: list[str]
    hard_count: int
    paused_count: int
