import json
from pathlib import Path

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "test-api-key")


@pytest.fixture
def brave_response():
    fixture_path = Path(__file__).parent / "fixtures" / "brave_response.json"
    with fixture_path.open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)
