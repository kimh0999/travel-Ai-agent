"""실제 Firestore 연결 확인 (자동 테스트와 분리). FIREBASE_SERVICE_ACCOUNT_JSON이 필요하다.

실행: backend 폴더에서  .venv/Scripts/python scripts/check_live_firestore.py
`_healthchecks` 컬렉션에 문서 1개를 쓰고 읽은 뒤 삭제한다.
"""
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.firebase import get_db  # noqa: E402
from app.schemas.common import utcnow  # noqa: E402


def main() -> int:
    if os.getenv("FIRESTORE_EMULATOR_HOST"):
        print("SKIP: FIRESTORE_EMULATOR_HOST가 설정되어 있어 에뮬레이터에 연결됩니다. 해제 후 실행하세요.")
        return 2
    if not get_settings().firebase_service_account_json:
        print("SKIP: FIREBASE_SERVICE_ACCOUNT_JSON이 없습니다.")
        return 2
    ref = get_db().collection("_healthchecks").document(f"check-{uuid.uuid4().hex[:8]}")
    ref.set({"at": utcnow()})
    ok = ref.get().exists
    ref.delete()
    print("OK: Firestore 쓰기/읽기/삭제 성공" if ok else "FAIL: 쓴 문서를 읽지 못했습니다")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
