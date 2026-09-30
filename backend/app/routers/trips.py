from fastapi import APIRouter, Body, Depends

from app.core.auth import AuthUser, current_user
from app.repositories import trips as repo
from app.repositories import users as users_repo
from app.repositories import versions as versions_repo
from app.schemas.course import CourseVersion, CourseVersionBrief, RevisionCreate
from app.schemas.trips import (PinRequest, Trip, TripCreate, TripDeletePreview, TripDeleteRequest,
                               TripDeleteResult, TripUpdate)
from app.services import course_generator, trip_deletion

router = APIRouter(prefix="/api/trips", tags=["trips"])


@router.post("", response_model=Trip, status_code=201)
def create_trip(body: TripCreate, user: AuthUser = Depends(current_user)):
    default_days = int(users_repo.get_settings_doc(user.uid).get("default_trip_days", 3))
    return repo.create(user.uid, body, default_days)


@router.get("", response_model=list[Trip])
def list_trips(user: AuthUser = Depends(current_user)):
    return repo.list_for_owner(user.uid)


@router.get("/{trip_id}", response_model=Trip)
def get_trip(trip_id: str, user: AuthUser = Depends(current_user)):
    return repo.get(user.uid, trip_id)


@router.put("/{trip_id}", response_model=Trip)
def update_trip(trip_id: str, body: TripUpdate, user: AuthUser = Depends(current_user)):
    return repo.update(user.uid, trip_id, body)


@router.get("/{trip_id}/delete-preview", response_model=TripDeletePreview)
def delete_preview(trip_id: str, user: AuthUser = Depends(current_user)):
    return trip_deletion.preview(user.uid, trip_id)


@router.delete("/{trip_id}", response_model=TripDeleteResult)
def delete_trip(trip_id: str, body: TripDeleteRequest = Body(default_factory=TripDeleteRequest),
                user: AuthUser = Depends(current_user)):
    return trip_deletion.delete_trip(user.uid, trip_id, body.delete_preference_ids)


@router.post("/{trip_id}/generate", response_model=CourseVersion, status_code=201)
def generate(trip_id: str, user: AuthUser = Depends(current_user)):
    return course_generator.generate_course(user.uid, trip_id)


@router.get("/{trip_id}/versions", response_model=list[CourseVersionBrief])
def list_versions(trip_id: str, user: AuthUser = Depends(current_user)):
    trip = repo.get(user.uid, trip_id)
    return [CourseVersionBrief(id=v["id"], kind=v["kind"], label=v["label"], title=v["course"]["title"],
                               created_at=v["created_at"], is_current=v["id"] == trip.get("current_version_id"))
            for v in versions_repo.list_for_trip(user.uid, trip_id)]


@router.get("/{trip_id}/versions/{version_id}", response_model=CourseVersion)
def get_version(trip_id: str, version_id: str, user: AuthUser = Depends(current_user)):
    repo.get(user.uid, trip_id)
    return versions_repo.get(user.uid, trip_id, version_id)


@router.post("/{trip_id}/versions/{version_id}/restore", response_model=Trip)
def restore_version(trip_id: str, version_id: str, user: AuthUser = Depends(current_user)):
    """이전 일정으로 되돌리기: 그 버전을 현재 코스로 지정한다(버전은 지우지 않는다)."""
    return course_generator.restore_version(user.uid, trip_id, version_id)


@router.post("/{trip_id}/pins", response_model=Trip)
def set_pin(trip_id: str, body: PinRequest, user: AuthUser = Depends(current_user)):
    """현재 코스의 장소를 고정(꼭 가기)하거나 고정을 푼다. 고정한 장소는 코스를 고쳐도 빠지지 않는다."""
    trip, _ = course_generator.set_pin(user.uid, trip_id, body.item_id, body.pinned)
    return trip


@router.post("/{trip_id}/versions", response_model=CourseVersion, status_code=201)
def save_revision(trip_id: str, body: RevisionCreate, user: AuthUser = Depends(current_user)):
    return course_generator.save_revision(user.uid, trip_id, body.parent_version_id, body.course, body.label)
