"""AI가 제안한 장소를 장소 검색으로 확인한다. 확인되지 않으면 '미확인 장소'로 표시한다(SPEC 9-2)."""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.clients.places_base import PlaceProvider, PlaceResult, PlaceSearchError
from app.schemas.common import utcnow
from app.schemas.course import CourseOut, StoredCourse, VerifiedPlace

logger = logging.getLogger("app.places")
MAX_VERIFY = 60


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _match(name: str, results: list[PlaceResult]) -> Optional[PlaceResult]:
    target = _norm(name)
    if not target:
        return None
    for r in results:
        cand = _norm(r.name)
        if cand and (cand == target or target in cand or cand in target):
            return r
    return None


def search_with_retry(provider: PlaceProvider, query: str, size: int = 5) -> list[PlaceResult]:
    """실패한 검색만 한 번 더 시도한다. 두 번 다 실패하면 PlaceSearchError."""
    try:
        return provider.search(query, size=size)
    except PlaceSearchError as e:
        logger.warning("place search failed, retrying once: %s", e)
        return provider.search(query, size=size)


def search_candidates(provider: PlaceProvider, destination: str, keywords: list[str], limit: int = 15) -> list[PlaceResult]:
    """키워드별로 검색한다. 일부 키워드가 실패해도 성공한 결과는 그대로 쓴다."""
    seen: set[str] = set()
    out: list[PlaceResult] = []
    for kw in keywords[:4]:
        try:
            results = search_with_retry(provider, f"{destination} {kw}")
        except PlaceSearchError as e:
            logger.warning("candidate search failed: %s", e)
            continue
        for r in results:
            if r.provider_id not in seen:
                seen.add(r.provider_id)
                out.append(r)
    return out[:limit]


def verify_course(provider: PlaceProvider, destination: str, course: CourseOut) -> StoredCourse:
    checked_at = utcnow()
    targets = [(d_i, i_i, item) for d_i, day in enumerate(course.days) for i_i, item in enumerate(day.items)
               if item.kind != "rest"][:MAX_VERIFY]

    def lookup(item) -> VerifiedPlace:
        keyword = item.search_keyword or item.name
        query = keyword if destination in keyword else f"{destination} {keyword}"
        try:
            results = search_with_retry(provider, query)
        except PlaceSearchError as e:
            logger.warning("verify search failed: %s", e)
            return VerifiedPlace(status="unverified", provider=provider.name, checked_at=checked_at)
        hit = _match(item.search_keyword or item.name, results) or _match(item.name, results)
        if provider.is_mock:
            return VerifiedPlace(status="mock", matched_name=hit.name if hit else None, provider=provider.name,
                                 checked_at=checked_at, address=hit.address if hit else None)
        if not hit:
            return VerifiedPlace(status="unverified", provider=provider.name, checked_at=checked_at)
        return VerifiedPlace(status="verified", matched_name=hit.name, place_url=hit.place_url, address=hit.address,
                             category=hit.category, provider=provider.name, checked_at=checked_at)

    with ThreadPoolExecutor(max_workers=6) as pool:
        verified = list(pool.map(lambda t: lookup(t[2]), targets))
    by_pos = {(d, i): v for (d, i, _), v in zip(targets, verified)}

    data = course.model_dump()
    for d_i, day in enumerate(data["days"]):
        for i_i, item in enumerate(day["items"]):
            place = by_pos.get((d_i, i_i))
            if place is None:
                place = VerifiedPlace(status="not_applicable" if item["kind"] == "rest" else "unverified",
                                      provider=provider.name)
            item["place"] = place.model_dump()
            item["travel_is_estimate"] = True
            item["cost_is_estimate"] = True
    return StoredCourse.model_validate(data)
