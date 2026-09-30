"""코스 생성 AI 응답 모델.

Claude 구조화 출력(output_format)과 도구 입력 스키마로 그대로 쓰므로 필드 기본값·dict 타입을 쓰지 않고,
선택값은 Optional(nullable)로만 표현한다. 숫자 범위·길이 같은 제약은 스키마에 넣지 않고
model_validator에서 검증한다(검증 실패 시 파이프라인이 1회 재시도하거나 도구 오류로 돌려준다).
"""
import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

TravelMode = Literal["walk", "bus", "subway", "train", "taxi", "car", "ferry", "other"]
ItemKind = Literal["place", "meal", "rest"]
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _check_len(value: Optional[str], name: str, max_len: int, required: bool = True) -> None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return
    if required and not value.strip():
        raise ValueError(f"{name} must not be empty")
    if len(value) > max_len:
        raise ValueError(f"{name} too long (>{max_len})")


class TravelLeg(BaseModel):
    mode: TravelMode
    minutes_estimate: int
    note: Optional[str]

    @model_validator(mode="after")
    def _check(self):
        if not 0 <= self.minutes_estimate <= 600:
            raise ValueError("minutes_estimate must be 0..600")
        _check_len(self.note, "note", 200, required=False)
        return self


class BackupPlace(BaseModel):
    """비가 오거나 문을 닫았을 때 갈 대체 장소."""
    name: str
    search_keyword: Optional[str]
    reason: str

    @model_validator(mode="after")
    def _check(self):
        _check_len(self.name, "backup.name", 100)
        _check_len(self.search_keyword, "backup.search_keyword", 100, required=False)
        _check_len(self.reason, "backup.reason", 200)
        return self


class CourseItem(BaseModel):
    item_id: str
    kind: ItemKind
    name: str
    search_keyword: Optional[str]
    reason: str
    applied_preference_ids: list[str]
    start_time: Optional[str]
    stay_minutes: int
    travel_from_prev: Optional[TravelLeg]
    cost_estimate_krw: Optional[int]
    cost_basis: Optional[str]
    backup: Optional[BackupPlace]

    @model_validator(mode="after")
    def _check(self):
        _check_len(self.item_id, "item_id", 20)
        if self.start_time is not None and not _TIME.match(self.start_time):
            raise ValueError("start_time must be HH:MM")
        _check_len(self.name, "name", 100)
        _check_len(self.reason, "reason", 400)
        _check_len(self.search_keyword, "search_keyword", 100, required=False)
        _check_len(self.cost_basis, "cost_basis", 200, required=False)
        if not 0 <= self.stay_minutes <= 720:
            raise ValueError("stay_minutes must be 0..720")
        if self.cost_estimate_krw is not None:
            if not 0 <= self.cost_estimate_krw <= 10_000_000:
                raise ValueError("cost_estimate_krw must be 0..10,000,000")
            if not self.cost_basis:
                raise ValueError("cost_basis is required when cost_estimate_krw is given")
        return self


class CourseDay(BaseModel):
    day_index: int
    date: Optional[str]
    theme: str
    items: list[CourseItem]

    @model_validator(mode="after")
    def _check(self):
        if not 1 <= self.day_index <= 14:
            raise ValueError("day_index must be 1..14")
        _check_len(self.theme, "theme", 100)
        if not 1 <= len(self.items) <= 12:
            raise ValueError("each day needs 1..12 items")
        times = [to_minutes(i.start_time) for i in self.items if i.start_time]
        if times != sorted(times):
            raise ValueError("start_time must be in order within a day")
        return self


class AppliedMemory(BaseModel):
    preference_id: str
    reason: str

    @model_validator(mode="after")
    def _check(self):
        _check_len(self.reason, "reason", 300)
        return self


class CourseOut(BaseModel):
    title: str
    summary_explanation: str
    assumptions: list[str]
    questions_for_user: list[str]
    days: list[CourseDay]
    applied_memories: list[AppliedMemory]

    @model_validator(mode="after")
    def _check(self):
        _check_len(self.title, "title", 100)
        _check_len(self.summary_explanation, "summary_explanation", 1000)
        if not 1 <= len(self.days) <= 14:
            raise ValueError("days must have 1..14 entries")
        if len(self.questions_for_user) > 2:
            raise ValueError("questions_for_user must have at most 2 entries")
        ids = [i.item_id for d in self.days for i in d.items]
        if len(ids) != len(set(ids)):
            raise ValueError("item_id must be unique")
        if [d.day_index for d in self.days] != list(range(1, len(self.days) + 1)):
            raise ValueError("day_index must be sequential from 1")
        return self


# ---------- 서버가 덧붙이는 정보 (AI가 생성하지 않음) ----------

INFO_NOT_VERIFIED = "영업시간·휴무일·입장료·예약 가능 여부: 최신 정보 미확인"


class VerifiedPlace(BaseModel):
    status: Literal["verified", "unverified", "mock", "not_applicable"]
    matched_name: Optional[str] = None
    place_url: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    provider: Optional[str] = None
    checked_at: Optional[datetime] = None
    info_notice: str = INFO_NOT_VERIFIED


class StoredCourseItem(CourseItem):
    place: VerifiedPlace
    pinned: bool = False  # 사용자가 고정한 장소 (서버가 여행의 고정 목록으로 표시)
    travel_is_estimate: bool = True  # 이동시간 조회 API를 연동하지 않으므로 항상 추정
    cost_is_estimate: bool = True  # 가격 조회 API가 없으므로 항상 추정


class StoredCourseDay(CourseDay):
    items: list[StoredCourseItem]


class StoredCourse(CourseOut):
    days: list[StoredCourseDay]


class AppliedMemoryOut(BaseModel):
    preference_id: str
    reason: str
    value: str
    category: str
    scope: str
    strength: str
    subject: str
    source_destinations: list[str]


class GenerationBasis(BaseModel):
    memory_ids: list[str]
    withheld_sensitive_ids: list[str]
    unknown_categories: list[str]
    past_trip_ids: list[str]
    place_candidates: int
    model: str
    is_mock: bool
    place_provider: str
    generated_at: datetime


class CourseVersion(BaseModel):
    id: str
    trip_id: str
    kind: Literal["original", "revision"]
    parent_version_id: Optional[str]
    label: str
    course: StoredCourse
    applied_memories: list[AppliedMemoryOut]
    generation_basis: Optional[GenerationBasis]
    warnings: list[str]
    changes: list[str] = []  # 이전 버전 대비 변경점 (수정본)
    changed_days: list[int] = []
    created_at: datetime


class CourseVersionBrief(BaseModel):
    id: str
    kind: Literal["original", "revision"]
    label: str
    title: str
    created_at: datetime
    is_current: bool


class RevisionCreate(BaseModel):
    parent_version_id: str = Field(max_length=64)
    course: CourseOut
    label: Optional[str] = Field(default=None, max_length=50)
