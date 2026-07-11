from unittest.mock import patch

from app import BraveAPIError


def test_index_returns_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Image Search" in response.data


def test_search_returns_results(client, api_key, brave_response):
    with patch("app.brave_image_search", return_value=brave_response["results"]):
        response = client.post("/search", json={"query": "black ferrari"})

    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 2
    assert data[0]["properties"]["url"] == "https://example.com/image1.jpg"


def test_search_missing_query_returns_400(client, api_key):
    response = client.post("/search", json={"query": ""})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Query is required"


def test_search_whitespace_query_returns_400(client, api_key):
    response = client.post("/search", json={"query": "   "})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Query is required"


def test_search_query_too_long_returns_400(client, api_key):
    response = client.post("/search", json={"query": "a" * 401})

    assert response.status_code == 400
    assert "too long" in response.get_json()["error"]


def test_search_missing_api_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    response = client.post("/search", json={"query": "black ferrari"})

    assert response.status_code == 503
    assert "Server API key not configured" in response.get_json()["error"]


def test_search_invalid_json_returns_400(client, api_key):
    response = client.post(
        "/search",
        data="not json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid JSON body"


def test_search_non_json_content_type_returns_400(client, api_key):
    response = client.post("/search", data="query=test")

    assert response.status_code == 400
    assert response.get_json()["error"] == "Request must be JSON"


def test_search_brave_api_error_returns_status(client, api_key):
    with patch(
        "app.brave_image_search",
        side_effect=BraveAPIError("Brave API error: 429", 502),
    ):
        response = client.post("/search", json={"query": "black ferrari"})

    assert response.status_code == 502
    assert response.get_json()["error"] == "Brave API error: 429"


def test_search_timeout_returns_504(client, api_key):
    with patch(
        "app.brave_image_search",
        side_effect=BraveAPIError("Search request timed out", 504),
    ):
        response = client.post("/search", json={"query": "black ferrari"})

    assert response.status_code == 504
    assert response.get_json()["error"] == "Search request timed out"


def test_search_brave_422_returns_422(client, api_key):
    with patch(
        "app.brave_image_search",
        side_effect=BraveAPIError("Option not in plan", 422),
    ):
        response = client.post("/search", json={"query": "black ferrari"})

    assert response.status_code == 422
    assert response.get_json()["error"] == "Option not in plan"
