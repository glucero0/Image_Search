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
    assert len(data["results"]) == 2
    assert data["results"][0]["properties"]["url"] == "https://example.com/image1.jpg"
    assert data["offset"] == 0
    assert data["count"] == 50
    assert data["has_more"] is False


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


def test_search_passes_search_options(client, api_key, brave_response):
    with patch(
        "app.brave_image_search", return_value=brave_response["results"]
    ) as mock_search:
        response = client.post(
            "/search",
            json={
                "query": "black ferrari",
                "safesearch": "off",
                "country": "GB",
                "search_lang": "en",
            },
        )

    assert response.status_code == 200
    mock_search.assert_called_once_with(
        "black ferrari",
        "test-api-key",
        safesearch="off",
        country="GB",
        search_lang="en",
        count=50,
        offset=0,
    )


def test_search_passes_pagination_options(client, api_key, brave_response):
    with patch(
        "app.brave_image_search", return_value=brave_response["results"]
    ) as mock_search:
        response = client.post(
            "/search",
            json={"query": "black ferrari", "count": 100, "offset": 1},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["offset"] == 1
    assert data["count"] == 100
    mock_search.assert_called_once_with(
        "black ferrari",
        "test-api-key",
        safesearch="strict",
        country="US",
        search_lang="en",
        count=100,
        offset=1,
    )


def test_search_rejects_offset_beyond_brave_cap(client, api_key):
    response = client.post(
        "/search",
        json={"query": "black ferrari", "count": 100, "offset": 2},
    )

    assert response.status_code == 400
    assert "offset must be between 0 and 1" in response.get_json()["error"]


def test_search_has_more_when_page_is_full(client, api_key):
    full_page = [{"properties": {"url": f"https://example.com/{i}.jpg"}} for i in range(50)]
    with patch("app.brave_image_search", return_value=full_page):
        response = client.post("/search", json={"query": "black ferrari", "offset": 1})

    assert response.status_code == 200
    assert response.get_json()["has_more"] is True


def test_search_invalid_count_returns_400(client, api_key):
    response = client.post(
        "/search",
        json={"query": "black ferrari", "count": 500},
    )

    assert response.status_code == 400
    assert "count" in response.get_json()["error"]


def test_search_invalid_offset_returns_400(client, api_key):
    response = client.post(
        "/search",
        json={"query": "black ferrari", "offset": 10},
    )

    assert response.status_code == 400
    assert "offset" in response.get_json()["error"]


def test_search_invalid_safesearch_returns_400(client, api_key):
    response = client.post(
        "/search",
        json={"query": "black ferrari", "safesearch": "moderate"},
    )

    assert response.status_code == 400
    assert "safesearch" in response.get_json()["error"]


def test_search_invalid_country_returns_400(client, api_key):
    response = client.post(
        "/search",
        json={"query": "black ferrari", "country": "USA"},
    )

    assert response.status_code == 400
    assert "country" in response.get_json()["error"]


def test_proxy_missing_url_returns_400(client):
    response = client.get("/proxy")

    assert response.status_code == 400
    assert response.get_json()["error"] == "url query parameter is required"


def test_proxy_rejects_unsafe_url(client):
    response = client.get("/proxy", query_string={"url": "https://127.0.0.1/a.jpg"})

    assert response.status_code == 400
    assert "disallowed" in response.get_json()["error"]


def test_proxy_rejects_unauthorized_url(client):
    response = client.get(
        "/proxy",
        query_string={"url": "https://example.com/not-from-search.jpg"},
    )

    assert response.status_code == 403
    assert "not authorized" in response.get_json()["error"]


def test_search_registers_proxy_urls(client, api_key, brave_response):
    from app import ALLOWED_PROXY_URLS

    with patch("app.brave_image_search", return_value=brave_response["results"]):
        response = client.post("/search", json={"query": "black ferrari"})

    assert response.status_code == 200
    assert "https://example.com/image1.jpg" in ALLOWED_PROXY_URLS
    assert "https://example.com/image2.png" in ALLOWED_PROXY_URLS


def test_proxy_returns_image(client):
    with patch(
        "app.fetch_proxied_image",
        return_value=(b"image-bytes", "image/jpeg"),
    ):
        response = client.get(
            "/proxy",
            query_string={"url": "https://example.com/image.jpg"},
        )

    assert response.status_code == 200
    assert response.data == b"image-bytes"
    assert response.mimetype == "image/jpeg"
