"""소프트 삭제(status=deleted)된 지 30일이 지난 기억을 물리 삭제한다. 운영에서 주기적으로(예: Render Cron Job) 실행.

실행: backend 폴더에서  .venv/Scripts/python scripts/purge_deleted.py [--days 30] [--dry-run]
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.cloud.firestore import FieldFilter  # noqa: E402

from app.core.firebase import get_db  # noqa: E402
from app.schemas.common import utcnow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cutoff = utcnow() - timedelta(days=args.days)
    db = get_db()
    targets = [s for s in db.collection("preferences").where(filter=FieldFilter("status", "==", "deleted")).stream()
               if (s.to_dict() or {}).get("deleted_at") and s.to_dict()["deleted_at"] < cutoff]
    print(f"대상 {len(targets)}개 (삭제 후 {args.days}일 경과)")
    if args.dry_run:
        return 0
    for i in range(0, len(targets), 300):
        batch = db.batch()
        for s in targets[i:i + 300]:
            batch.delete(s.reference)
        batch.commit()
    print("완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
