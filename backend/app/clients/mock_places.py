"""PLACE_PROVIDER=mock: 외부 호출 없이 결정적인 모의 장소를 돌려준다. 결과는 항상 mock으로 표시된다."""
import hashlib

from app.clients.places_base import PlaceResult

_KEYWORD_PLACES = {
    "카페": ["바다전망 카페", "골목 로스터리 카페"],
    "자연": ["해안 산책로", "전망 공원"],
    "음식": ["향토 음식점", "해산물 식당"],
    "문화": ["시립 미술관", "근대 역사관"],
    "쇼핑": ["중앙 시장", "아케이드 상가"],
    "액티비티": ["해양 레저센터", "케이블카 승강장"],
    "휴양": ["해변 쉼터", "온천 휴게소"],
}
_DEFAULT = ["대표 관광지", "해변", "전통시장", "전망대"]


class MockPlaceProvider:
    name = "mock"
    is_mock = True

    def search(self, query: str, size: int = 5) -> list[PlaceResult]:
        parts = query.split()
        region = parts[0] if parts else "여행지"
        rest = " ".join(parts[1:])
        names = next((v for k, v in _KEYWORD_PLACES.items() if k in rest), None)
        if names is None:
            names = [rest] if rest else _DEFAULT
        results = []
        for n in names[:size]:
            full = n if n.startswith(region) else f"{region} {n}"
            pid = hashlib.sha1(full.encode()).hexdigest()[:10]
            results.append(PlaceResult(provider_id=f"mock-{pid}", name=full, category="모의 데이터",
                                       address=f"{region} (모의 주소)", place_url=None, x=None, y=None))
        return results
