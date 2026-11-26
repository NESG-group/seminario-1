from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from demo.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a FastAPI TestClient bound to the real application instance."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _single_user_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test in single-user mode, whatever the local .env says.

    Multi-user tests opt in by setting ``settings.user_jwt_secret`` themselves.
    """
    from demo.config import settings

    monkeypatch.setattr(settings, "user_jwt_secret", None)
