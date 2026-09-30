"""firebase-admin 초기화와 Firestore 클라이언트.

- 운영: FIREBASE_SERVICE_ACCOUNT_JSON(JSON 문자열 또는 파일 경로)으로 초기화.
- 에뮬레이터: FIRESTORE_EMULATOR_HOST / FIREBASE_AUTH_EMULATOR_HOST가 설정되면
  서비스 계정 없이 FIREBASE_PROJECT_ID만으로 초기화한다.
"""
import json
import os
from functools import lru_cache

import firebase_admin
from firebase_admin import credentials, firestore as admin_firestore
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from app.core.config import get_settings


def _load_service_account(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    with open(raw, encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def get_app() -> firebase_admin.App:
    settings = get_settings()
    if settings.firebase_service_account_json:
        cred = credentials.Certificate(_load_service_account(settings.firebase_service_account_json))
        options = {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None
        return firebase_admin.initialize_app(cred, options)
    if settings.use_emulator or os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
        if not settings.firebase_project_id:
            raise RuntimeError("에뮬레이터 모드에서는 FIREBASE_PROJECT_ID가 필요합니다.")
        return firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON이 설정되지 않았습니다. README의 인증 설정을 참고하세요.")


@lru_cache
def get_db() -> firestore.Client:
    settings = get_settings()
    app = get_app()
    if settings.use_emulator and not settings.firebase_service_account_json:
        # 에뮬레이터는 인증이 필요 없다. ADC 탐색을 피하려고 익명 자격증명으로 직접 생성한다.
        return firestore.Client(project=settings.firebase_project_id, credentials=AnonymousCredentials())
    return admin_firestore.client(app)
