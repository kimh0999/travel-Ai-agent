"""기억 변경안: AI 추출 모델(구조화 출력용)과 API 모델."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Category, ProposalStatus, ProposalType, Strength, Subject

SituationalFactor = Literal["weather", "companion", "condition", "crowd_timing", "other"]
Certainty = Literal["clear", "guess"]  # clear: 사용자가 분명히 말함 / guess: 확신할 수 없는 추정(확인 필요)


class Situational(BaseModel):
    is_situational: bool
    factor: Optional[SituationalFactor]
    reason: str

    @model_validator(mode="after")
    def _check(self):
        if len(self.reason) > 300:
            raise ValueError("reason too long")
        return self


class ProposalDraft(BaseModel):
    type: ProposalType
    target_preference_id: Optional[str]
    category: Category
    strength: Strength
    subject: Subject
    before: Optional[str]
    after: Optional[str]
    evidence_text: str
    evidence_item_id: Optional[str]
    situational: Situational

    @model_validator(mode="after")
    def _check(self):
        if self.type in ("update", "deactivate") and not self.target_preference_id:
            raise ValueError("update/deactivate requires target_preference_id")
        if self.type in ("add", "update") and not (self.after and self.after.strip()):
            raise ValueError("add/update requires after")
        if self.after and len(self.after) > 200:
            raise ValueError("after too long")
        if not self.evidence_text.strip() or len(self.evidence_text) > 500:
            raise ValueError("evidence_text must be 1..500 chars")
        return self


class ProposalExtraction(BaseModel):
    proposals: list[ProposalDraft]
    excluded_notes: list[str]

    @model_validator(mode="after")
    def _check(self):
        if len(self.proposals) > 6:
            raise ValueError("at most 6 proposals")
        return self


class MemoryProposal(BaseModel):
    id: str
    owner_uid: str
    trip_id: Optional[str]
    conversation_id: Optional[str] = None
    feedback_id: Optional[str]
    type: ProposalType
    target_preference_id: Optional[str]
    category: Category
    strength: Strength
    subject: Subject
    before: Optional[str]
    after: Optional[str]
    edited_value: Optional[str]
    evidence_text: str
    evidence_item_id: Optional[str]
    situational: Situational
    applies_to: Optional[str] = None  # 적용 범위 설명 (예: 모든 여행, 부모님과 갈 때)
    certainty: Certainty = "clear"
    question: Optional[str] = None  # guess일 때 사용자에게 확인할 질문
    status: ProposalStatus
    result_preference_id: Optional[str]
    is_mock: bool
    created_at: datetime
    decided_at: Optional[datetime]


class ProposalGenerateResult(BaseModel):
    proposals: list[MemoryProposal]
    excluded_notes: list[str]
    discarded: list[str]


class ApproveRequest(BaseModel):
    edited_value: Optional[str] = Field(default=None, min_length=1, max_length=200)


class ApproveResult(BaseModel):
    proposal: MemoryProposal
    preference_id: Optional[str]
    already_decided: bool
