from fastapi import APIRouter, Depends, Response

from app.core.auth import AuthUser, current_user
from app.repositories import feedback as repo
from app.repositories import proposals as proposals_repo
from app.schemas.feedback import Feedback, FeedbackCreate, FeedbackUpdate

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/trips/{trip_id}/feedback", response_model=Feedback, status_code=201)
def create_feedback(trip_id: str, body: FeedbackCreate, user: AuthUser = Depends(current_user)):
    # 피드백 저장만 한다. 장기 기억은 사용자가 변경안을 승인해야만 바뀐다.
    return repo.create(user.uid, trip_id, body)


@router.get("/trips/{trip_id}/feedback", response_model=list[Feedback])
def list_feedback(trip_id: str, user: AuthUser = Depends(current_user)):
    return repo.list_for_trip(user.uid, trip_id)


@router.put("/feedback/{feedback_id}", response_model=Feedback)
def update_feedback(feedback_id: str, body: FeedbackUpdate, user: AuthUser = Depends(current_user)):
    return repo.update(user.uid, feedback_id, body)


@router.delete("/feedback/{feedback_id}", status_code=204)
def delete_feedback(feedback_id: str, user: AuthUser = Depends(current_user)):
    fb = repo.get(user.uid, feedback_id)
    repo.delete(user.uid, feedback_id)
    # 삭제한 피드백에서 나온 미결정 변경안도 함께 지운다(승인·거절 기록은 유지).
    proposals_repo.delete_pending(user.uid, fb["trip_id"], feedback_id=feedback_id)
    return Response(status_code=204)
