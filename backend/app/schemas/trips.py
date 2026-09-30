from datetime import date, datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import TripStatus

MAX_TRIP_DAYS = 14
TripTransport = Literal["car", "public", "mixed"]  # 자가용·렌터카 / 대중교통 / 섞어서


class Companion(BaseModel):
    relation: str = Field(min_length=1, max_length=30)  # 예: 친구, 부모님, 아이(7세)
    note: Optional[str] = Field(default=None, max_length=100)


class Budget(BaseModel):
    amount: int = Field(ge=0, le=100_000_000)
    currency: Literal["KRW"] = "KRW"
    per: Literal["person", "group"]  # 1인당 / 전체
    unit: Literal["day", "trip"]  # 1일 / 여행 전체


def _resolve_dates(start: Optional[date], end: Optional[date], days: Optional[int]):
    if end and not start:
        raise ValueError("종료일만 입력할 수 없습니다. 시작일을 함께 입력하세요.")
    if start and end:
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        span = (end - start).days + 1
        if days is not None and days != span:
            raise ValueError("기간(일수)이 날짜 범위와 맞지 않습니다.")
        days = span
    elif start and days:
        end = start + timedelta(days=days - 1)
    if days is not None and not (1 <= days <= MAX_TRIP_DAYS):
        raise ValueError(f"여행 기간은 1~{MAX_TRIP_DAYS}일이어야 합니다.")
    return start, end, days


class PinnedPlace(BaseModel):
    item_id: str = Field(max_length=20)
    name: str = Field(max_length=100)


class PinRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=20)
    pinned: bool


class TripCreate(BaseModel):
    destination: str = Field(min_length=1, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, le=MAX_TRIP_DAYS)
    period_hint: Optional[str] = Field(default=None, max_length=40)  # 날짜 미정일 때 대략의 시기 (예: 2026년 10월)
    transport: Optional[TripTransport] = None
    companions: list[Companion] = Field(default_factory=list, max_length=10)
    budget: Optional[Budget] = None
    conditions: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self):
        self.destination = self.destination.strip()
        if not self.destination:
            raise ValueError("목적지를 입력하세요.")
        self.start_date, self.end_date, self.days = _resolve_dates(self.start_date, self.end_date, self.days)
        return self


class TripUpdate(BaseModel):
    destination: Optional[str] = Field(default=None, min_length=1, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, le=MAX_TRIP_DAYS)
    period_hint: Optional[str] = Field(default=None, max_length=40)
    transport: Optional[TripTransport] = None
    companions: Optional[list[Companion]] = Field(default=None, max_length=10)
    budget: Optional[Budget] = None
    conditions: Optional[str] = Field(default=None, max_length=500)
    status: Optional[TripStatus] = None


class Trip(BaseModel):
    id: str
    owner_uid: str
    destination: str
    start_date: Optional[date]
    end_date: Optional[date]
    days: int
    days_is_default: bool
    period_hint: Optional[str] = None
    transport: Optional[TripTransport] = None
    pinned_places: list[PinnedPlace] = []
    companions: list[Companion]
    budget: Optional[Budget]
    conditions: Optional[str]
    status: TripStatus
    current_version_id: Optional[str]
    created_at: datetime
    updated_at: datetime


class TripDeleteRequest(BaseModel):
    delete_preference_ids: list[str] = Field(default_factory=list, max_length=200)


class TripDeletePreviewItem(BaseModel):
    id: str
    value: str
    category: str
    only_from_this_trip: bool


class TripDeletePreview(BaseModel):
    trip_id: str
    destination: str
    learned_preferences: list[TripDeletePreviewItem]
    counts: dict[str, int]


class TripDeleteResult(BaseModel):
    deleted: dict[str, int]
    kept_learned_preference_ids: list[str]
    deleted_preference_ids: list[str]
