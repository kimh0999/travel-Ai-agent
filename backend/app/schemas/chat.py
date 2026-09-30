from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import Category, ProposalType, Strength, Subject, TripStatus
from app.schemas.course import CourseDay
from app.schemas.proposals import Certainty
from app.schemas.trips import MAX_TRIP_DAYS, TripTransport

TurnStatus = Literal["running", "done", "failed"]


class TurnCreate(BaseModel):
    # 클라이언트가 만든 요청 ID. 같은 ID로 다시 보내면 새로 실행하지 않고 기존 턴을 돌려준다(중복 방지).
    client_turn_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    trip_id: Optional[str] = Field(default=None, max_length=64)  # 화면에서 선택한 현재 작업 여행
    message: str = Field(min_length=1, max_length=2000)


class TurnError(BaseModel):
    code: str
    message: str


class Turn(BaseModel):
    id: str
    conversation_id: str
    trip_id: Optional[str]
    status: TurnStatus
    attempt: int
    message: str
    reply: str
    cards: list[dict[str, Any]]
    error: Optional[TurnError]
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=60)
    trip_id: Optional[str] = Field(default=None, max_length=64)


class Message(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    cards: list[dict[str, Any]] = []
    seq: int
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    trip_id: Optional[str]
    trip_destination: Optional[str]
    summary: Optional[str]
    message_count: int
    last_message_at: Optional[datetime]
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[Message]
    open_turn: Optional[Turn] = None  # 아직 끝나지 않았거나 실패한 마지막 턴 (재접속·재시도용)


# ---------- AI 도구 인자 ----------
# 서버가 Pydantic으로 다시 검증한다. uid는 인자로 받지 않고 서버 세션에서 주입한다.

class NoArgs(BaseModel):
    pass


class TripRef(BaseModel):
    trip_id: str = Field(max_length=64)


class CreateTripArgs(BaseModel):
    destination: str = Field(min_length=1, max_length=50)
    start_date: Optional[date] = Field(default=None, description="확정된 시작일만. 상대 날짜는 오늘 기준 실제 날짜로 바꿔서.")
    end_date: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, le=MAX_TRIP_DAYS, description="일수 (2박 3일이면 3)")
    period_hint: Optional[str] = Field(default=None, max_length=40,
                                       description="날짜가 미정일 때 대략의 시기를 실제 연월로 (예: '2026년 10월')")
    transport: Optional[TripTransport] = Field(default=None, description="car=자가용·렌터카, public=대중교통, mixed=섞어서")
    companions: list[str] = Field(default_factory=list, max_length=10, description="동행인 관계 (예: 엄마, 친구)")


class UpdateTripArgs(BaseModel):
    trip_id: str = Field(max_length=64)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, le=MAX_TRIP_DAYS)
    period_hint: Optional[str] = Field(default=None, max_length=40)
    transport: Optional[TripTransport] = None
    companions: Optional[list[str]] = Field(default=None, max_length=10)
    status: Optional[TripStatus] = Field(default=None, description="여행을 다녀왔으면 completed")


class PreferencesArgs(BaseModel):
    trip_id: Optional[str] = Field(default=None, max_length=64, description="이 여행 한정 조건도 함께 보려면 지정")


class SearchPlacesArgs(BaseModel):
    query: str = Field(min_length=1, max_length=100, description="지역명을 포함한 검색어 (예: 부산 해운대 카페)")


class GenerateCourseArgs(BaseModel):
    trip_id: str = Field(max_length=64)
    request_note: Optional[str] = Field(default=None, max_length=500,
                                        description="이번 코스에 반영할 사용자 요청 (예: 바다 보이는 카페 위주)")


class ReviseCourseArgs(BaseModel):
    trip_id: str = Field(max_length=64)
    base_version_id: str = Field(max_length=64, description="get_course로 확인한 현재 version_id")
    days: list[CourseDay] = Field(min_length=1, max_length=MAX_TRIP_DAYS,
                                  description="바꾸는 날만 전체 내용으로. 보내지 않은 날은 그대로 유지된다.")
    changes: list[str] = Field(min_length=1, max_length=8,
                               description="사용자에게 보여줄 변경점 (예: '2일차 시장 방문 제외', '카페 체류 30분 추가')")
    label: Optional[str] = Field(default=None, max_length=40)


class PinPlaceArgs(BaseModel):
    trip_id: str = Field(max_length=64)
    item_id: str = Field(max_length=20)
    pinned: bool = True


class TripConditionArgs(BaseModel):
    trip_id: str = Field(max_length=64)
    category: Category
    text: str = Field(min_length=1, max_length=200, description="이번 여행에만 적용할 조건 (예: 엄마와 가서 덜 걷기)")
    subject: Subject = "self"


class ProposeMemoryArgs(BaseModel):
    type: ProposalType = "add"
    target_preference_id: Optional[str] = Field(default=None, max_length=64, description="update/deactivate 대상 기억 id")
    category: Category
    strength: Strength = "soft"
    subject: Subject = "self"
    statement: Optional[str] = Field(default=None, max_length=200, description="저장할 취향 문장 (deactivate면 비움)")
    applies_to: str = Field(min_length=1, max_length=60, description="적용 범위 (예: 모든 여행, 부모님과 갈 때)")
    evidence_text: str = Field(min_length=1, max_length=500, description="사용자가 이 대화에서 한 말을 그대로 인용")
    certainty: Certainty = Field(description="clear=사용자가 분명히 말함, guess=확신할 수 없는 추정")
    question: Optional[str] = Field(default=None, max_length=200, description="guess일 때 사용자에게 확인할 질문")
    trip_id: Optional[str] = Field(default=None, max_length=64, description="근거가 된 여행")


class AskUserArgs(BaseModel):
    question: str = Field(min_length=1, max_length=200)
    options: list[str] = Field(default_factory=list, max_length=4, description="버튼으로 보여줄 짧은 답 (각 20자 이내)")
