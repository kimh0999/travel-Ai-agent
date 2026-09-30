"""Firebase ID 토큰 검증 의존성. 사용자 식별은 오직 검증된 토큰의 uid로만 한다."""
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth

from app.core.errors import AppError
from app.core.firebase import get_app

_bearer = HTTPBearer(auto_error=False, description="Firebase ID 토큰")


@dataclass(frozen=True)
class AuthUser:
    uid: str
    email: Optional[str]


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> AuthUser:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise AppError(401, "UNAUTHENTICATED", "로그인이 필요합니다.")
    try:
        decoded = auth.verify_id_token(creds.credentials, app=get_app())
    except auth.CertificateFetchError:
        raise AppError(503, "AUTH_UNAVAILABLE", "인증 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.")
    except (auth.InvalidIdTokenError, ValueError):
        raise AppError(401, "UNAUTHENTICATED", "로그인 정보가 유효하지 않습니다. 다시 로그인하세요.")
    return AuthUser(uid=decoded["uid"], email=decoded.get("email"))
