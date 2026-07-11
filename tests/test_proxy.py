from unittest.mock import MagicMock, patch

import pytest
import requests
import socket

from app import (
    ProxyError,
    fetch_proxied_image,
    is_safe_image_url,
    resolve_public_ip,
    validate_country,
    validate_proxy_url,
    validate_safesearch,
    validate_search_lang,
)


def _public_dns_result(ip="93.184.216.34"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


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


def test_validate_proxy_url_rejects_ftp_scheme():
    with pytest.raises(ProxyError, match="Invalid or disallowed image URL"):
        validate_proxy_url("ftp://example.com/image.jpg")


def test_resolve_public_ip_rejects_private_address():
    with patch("app.socket.getaddrinfo", return_value=_public_dns_result("10.0.0.5")):
        with pytest.raises(ProxyError, match="disallowed address"):
            resolve_public_ip("evil.example.com")


def test_resolve_public_ip_returns_public_address():
    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        assert resolve_public_ip("example.com") == "93.184.216.34"


def test_fetch_proxied_image_returns_bytes():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": "4",
    }
    mock_response.iter_content.return_value = [b"test"]

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.Session", return_value=mock_session):
            image_data, content_type = fetch_proxied_image(
                "https://example.com/image.jpg"
            )

    assert image_data == b"test"
    assert content_type == "image/jpeg"
    mock_session.get.assert_called_once()


def test_fetch_proxied_image_rejects_non_image_content_type():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html></html>"]

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.Session", return_value=mock_session):
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

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.Session", return_value=mock_session):
            with pytest.raises(ProxyError, match="too large") as exc_info:
                fetch_proxied_image("https://example.com/big.jpg")

    assert exc_info.value.status_code == 413


def test_fetch_proxied_image_timeout_raises():
    mock_session = MagicMock()
    mock_session.get.side_effect = requests.Timeout("timed out")

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.Session", return_value=mock_session):
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
