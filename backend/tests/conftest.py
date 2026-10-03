import pytest

from app.api.dependencies import get_web_search_service
from app.core.config import Settings
from app.main import app
from app.services.web_search_service import WebSearchService


@pytest.fixture(autouse=True)
def isolate_external_search():
    previous = app.dependency_overrides.copy()
    # Unit/API regressions never use credentials from a developer's .env.
    app.dependency_overrides[get_web_search_service] = lambda: WebSearchService(Settings(_env_file=None, ENABLE_WEB_SEARCH=False))
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
