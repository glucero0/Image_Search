from unittest.mock import MagicMock, patch

import pytest
import requests

from app import (
    ProxyError,
    fetch_proxied_image,
    is_safe_image_url,
    validate_country,
    validate_safesearch,
    validate_search_lang,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/image.jpg",
        "http://cdn.example.org/photo.png",
    ],
)
def test_is_safe_image_url_allows_public_urls(url):
    assert is_safe_image_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/image.jpg",
        "https://localhost/image.jpg",
        "https://127.0.0.1/image.jpg",
        "https://192.168.1.10/image.jpg",
        "https://10.0.0.5/image.jpg",
        "not-a-url",
        "",
    ],
)
def test_is_safe_image_url_blocks_unsafe_urls(url):
    assert is_safe_image_url(url) is False


def test_fetch_proxied_image_returns_bytes():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": "4",
    }
    mock_response.iter_content.return_value = [b"test"]

    with patch("app.requests.get", return_value=mock_response):
        image_data, content_type = fetch_proxied_image(
            "https://example.com/image.jpg"
        )

    assert image_data == b"test"
    assert content_type == "image/jpeg"


def test_fetch_proxied_image_rejects_non_image_content_type():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html></html>"]

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(ProxyError, match="did not return an image"):
            fetch_proxied_image("https://example.com/page")


def test_fetch_proxied_image_rejects_oversized_image():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": str(16 * 1024 * 1024),
    }
    mock_response.iter_content.return_value = []

    with patch("app.requests.get", return_value=mock_response):
        with pytest.raises(ProxyError, match="too large") as exc_info:
            fetch_proxied_image("https://example.com/big.jpg")

    assert exc_info.value.status_code == 413


def test_fetch_proxied_image_timeout_raises():
    with patch("app.requests.get", side_effect=requests.Timeout("timed out")):
        with pytest.raises(ProxyError, match="timed out") as exc_info:
            fetch_proxied_image("https://example.com/image.jpg")

    assert exc_info.value.status_code == 504


def test_validate_safesearch_defaults_and_accepts_values():
    assert validate_safesearch(None) == "strict"
    assert validate_safesearch("off") == "off"
    assert validate_safesearch("STRICT") == "strict"


def test_validate_safesearch_rejects_invalid_value():
    with pytest.raises(ValueError, match="safesearch"):
        validate_safesearch("moderate")


def test_validate_country_defaults_and_accepts_values():
    assert validate_country(None) == "US"
    assert validate_country("gb") == "GB"
    assert validate_country("all") == "ALL"


def test_validate_country_rejects_invalid_value():
    with pytest.raises(ValueError, match="country"):
        validate_country("USA")


def test_validate_search_lang_defaults_and_accepts_values():
    assert validate_search_lang(None) == "en"
    assert validate_search_lang("ES") == "es"


def test_validate_search_lang_rejects_invalid_value():
    with pytest.raises(ValueError, match="search_lang"):
        validate_search_lang("e")
