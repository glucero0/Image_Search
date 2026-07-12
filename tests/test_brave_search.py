from unittest.mock import MagicMock, patch

import pytest
import requests

from app import BraveAPIError, brave_image_search


def test_brave_image_search_returns_results(brave_response):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = brave_response

    with patch("app.requests.get", return_value=mock_response) as mock_get:
        results = brave_image_search(
            "black ferrari",
            "test-key",
            safesearch="off",
            country="GB",
            search_lang="en",
        )

    assert len(results) == 2
    assert results[0]["properties"]["url"] == "https://example.com/image1.jpg"
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["timeout"] == (5, 30)
    assert kwargs["params"]["q"] == "black ferrari"
    assert kwargs["params"]["safesearch"] == "off"
    assert kwargs["params"]["country"] == "GB"
    assert kwargs["params"]["search_lang"] == "en"
    assert kwargs["params"]["count"] == 50
    assert kwargs["params"]["offset"] == 0


def test_brave_image_search_missing_results_key():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    with patch("app.requests.get", return_value=mock_response):
        results = brave_image_search("query", "test-key")

    assert results == []


def test_brave_image_search_403_raises():
    mock_response = MagicMock()
    mock_response.status_code = 403

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(BraveAPIError, match="Access Denied") as exc_info:
            brave_image_search("query", "test-key")

    assert exc_info.value.status_code == 502


def test_brave_image_search_422_raises_with_detail():
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.json.return_value = {
        "error": {"detail": "Option not in plan"}
    }

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(BraveAPIError, match="Option not in plan") as exc_info:
            brave_image_search("query", "test-key")

    assert exc_info.value.status_code == 422
    assert "Brave Search plan that includes images" in str(exc_info.value)


def test_brave_image_search_422_validation_error_omits_plan_hint():
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.json.return_value = {
        "error": {"detail": "Unable to validate request parameter(s)"}
    }

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(BraveAPIError, match="Unable to validate") as exc_info:
            brave_image_search("query", "test-key", search_lang="jp")

    assert "Brave Search plan that includes images" not in str(exc_info.value)


@pytest.mark.parametrize("status_code", [429, 500, 502])
def test_brave_image_search_non_200_raises(status_code):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.side_effect = ValueError("invalid json")

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(BraveAPIError, match=f"Brave API error: {status_code}"):
            brave_image_search("query", "test-key")


def test_brave_image_search_timeout_raises():
    with patch("app.requests.get", side_effect=requests.Timeout("timed out")):
        with pytest.raises(BraveAPIError, match="timed out") as exc_info:
            brave_image_search("query", "test-key")

    assert exc_info.value.status_code == 504


def test_brave_image_search_connection_error_raises():
    with patch(
        "app.requests.get",
        side_effect=requests.ConnectionError("connection failed"),
    ):
        with pytest.raises(BraveAPIError, match="Failed to reach Brave API"):
            brave_image_search("query", "test-key")


def test_brave_image_search_invalid_json_raises():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid json")

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(BraveAPIError, match="Invalid response from Brave API"):
            brave_image_search("query", "test-key")
