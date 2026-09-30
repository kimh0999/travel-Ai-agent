"""Firebase Emulator(Auth, Firestore) + AI_MODE=mock + PLACE_PROVIDER=mock 환경 테스트.

`npm test`(firebase emulators:exec)로 실행하면 에뮬레이터 호스트 환경변수가 자동으로 설정된다.
"""
import os
import uuid

os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-travel")
os.environ["AI_MODE"] = "mock"
os.environ["PLACE_PROVIDER"] = "mock"
os.environ.pop("FIREBASE_SERVICE_ACCOUNT_JSON", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PROJECT = os.environ["FIREBASE_PROJECT_ID"]
FS_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST")
AUTH_HOST = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")

if not FS_HOST or not AUTH_HOST:
    raise RuntimeError("Firebase Emulator가 필요합니다. 루트에서 `npm test`로 실행하세요.")


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_emulators():
    from app.clients import mock_ai
    mock_ai.FAILURES.clear()
    httpx.delete(f"http://{FS_HOST}/emulator/v1/projects/{PROJECT}/databases/(default)/documents").raise_for_status()
    httpx.delete(f"http://{AUTH_HOST}/emulator/v1/projects/{PROJECT}/accounts").raise_for_status()
    yield


def _sign_up(email: str) -> str:
    r = httpx.post(
        f"http://{AUTH_HOST}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-api-key",
        json={"email": email, "password": "password123", "returnSecureToken": True},
    )
    r.raise_for_status()
    return r.json()["idToken"]


class ApiUser:
    def __init__(self, client: TestClient, token: str):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.headers, **kw)

    def put(self, url, **kw):
        return self.client.put(url, headers=self.headers, **kw)

    def delete(self, url, **kw):
        return self.client.request("DELETE", url, headers=self.headers, **kw)


@pytest.fixture()
def make_user(client):
    def _make(name: str = "user") -> ApiUser:
        return ApiUser(client, _sign_up(f"{name}-{uuid.uuid4().hex[:8]}@example.com"))
    return _make


@pytest.fixture()
def alice(make_user):
    return make_user("alice")


@pytest.fixture()
def bob(make_user):
    return make_user("bob")


@pytest.fixture()
def ai_calls():
    """mock AI가 실제로 받은 요청 payload 기록 (테스트 2·4·5·10 검증용)."""
    from app.clients import mock_ai
    mock_ai.CALLS.clear()
    return mock_ai.CALLS
