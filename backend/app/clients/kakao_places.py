"""카카오 로컬 API - 키워드로 장소 검색.

공식 문서(developers.kakao.com/docs/latest/ko/local/dev-guide) 확인 내용:
GET https://dapi.kakao.com/v2/local/search/keyword.json, 헤더 Authorization: KakaoAK {REST_API_KEY},
파라미터 query(필수), size(1~15). 응답 documents: id, place_name, category_name, address_name,
road_address_name, place_url, x, y 등. 영업시간·가격 필드는 제공되지 않는다.
"""
import httpx

from app.clients.places_base import PlaceResult, PlaceSearchError

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class KakaoPlaceProvider:
    name = "kakao"
    is_mock = False

    def __init__(self, rest_api_key: str, timeout: float = 5.0):
        if not rest_api_key:
            raise RuntimeError("PLACE_PROVIDER=kakao에는 KAKAO_REST_API_KEY가 필요합니다.")
        self._client = httpx.Client(timeout=timeout, headers={"Authorization": f"KakaoAK {rest_api_key}"})

    def search(self, query: str, size: int = 5) -> list[PlaceResult]:
        try:
            r = self._client.get(KAKAO_KEYWORD_URL, params={"query": query[:100], "size": max(1, min(size, 15))})
            r.raise_for_status()
            docs = r.json().get("documents", [])
        except (httpx.HTTPError, ValueError) as e:
            raise PlaceSearchError(f"카카오 장소 검색 실패: {e.__class__.__name__}") from e
        return [
            PlaceResult(
                provider_id=str(d.get("id", "")),
                name=d.get("place_name", ""),
                category=d.get("category_name", ""),
                address=d.get("road_address_name") or d.get("address_name", ""),
                place_url=d.get("place_url") or None,
                x=d.get("x"),
                y=d.get("y"),
            )
            for d in docs
            if d.get("place_name")
        ]
