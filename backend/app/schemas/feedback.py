from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class VisitFeedback(BaseModel):
    item_id: str = Field(min_length=1, max_length=20)
    place_name: str = Field(min_length=1, max_length=100)
    visited: bool
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self):
        if not self.visited and self.rating is not None:
            raise ValueError("방문하지 않은 장소에는 평점을 줄 수 없습니다.")
        return self


class FeedbackCreate(BaseModel):
    version_id: Optional[str] = Field(default=None, max_length=64)
    visits: list[VisitFeedback] = Field(default_factory=list, max_length=100)
    overall_text: Optional[str] = Field(default=None, max_length=2000)
    overall_rating: Optional[int] = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _check(self):
        if self.overall_text is not None:
            self.overall_text = self.overall_text.strip() or None
        if not self.overall_text and not self.visits and self.overall_rating is None:
            raise ValueError("피드백 내용을 하나 이상 입력하세요.")
        ids = [v.item_id for v in self.visits]
        if len(ids) != len(set(ids)):
            raise ValueError("같은 장소 피드백이 중복되었습니다.")
        return self


class FeedbackUpdate(BaseModel):
    visits: Optional[list[VisitFeedback]] = Field(default=None, max_length=100)
    overall_text: Optional[str] = Field(default=None, max_length=2000)
    overall_rating: Optional[int] = Field(default=None, ge=1, le=5)


class Feedback(BaseModel):
    id: str
    owner_uid: str
    trip_id: str
    version_id: Optional[str]
    visits: list[VisitFeedback]
    overall_text: Optional[str]
    overall_rating: Optional[int]
    created_at: datetime
    updated_at: datetime
