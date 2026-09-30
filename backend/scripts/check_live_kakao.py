"""실제 카카오 로컬 API 연결 확인 (자동 테스트와 분리). KAKAO_REST_API_KEY가 필요하다.

실행: backend 폴더에서  .venv/Scripts/python scripts/check_live_kakao.py [검색어]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.kakao_places import KakaoPlaceProvider  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> int:
    key = get_settings().kakao_rest_api_key
    if not key:
        print("SKIP: KAKAO_REST_API_KEY가 없습니다.")
        return 2
    query = " ".join(sys.argv[1:]) or "부산 해운대 카페"
    results = KakaoPlaceProvider(key).search(query, size=5)
    print(f"OK: '{query}' 결과 {len(results)}개")
    for r in results:
        print(f"- {r.name} | {r.category} | {r.address} | {r.place_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
