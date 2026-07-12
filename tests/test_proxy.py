from unittest.mock import MagicMock, patch

import pytest
import requests
import socket

from app import (
    ProxyError,
    ValidationError,
    build_search_response,
    fetch_proxied_image,
    is_safe_image_url,
    max_offset_for_count,
    register_proxy_urls_from_results,
    resolve_public_ip,
    validate_country,
    validate_count,
    validate_offset,
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


def test_fetch_proxied_image_requires_authorization():
    with pytest.raises(ProxyError, match="not authorized") as exc_info:
        fetch_proxied_image("https://example.com/image.jpg")

    assert exc_info.value.status_code == 403


def test_fetch_proxied_image_returns_bytes():
    register_proxy_urls_from_results(
        [{"properties": {"url": "https://example.com/image.jpg"}}]
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": "4",
    }
    mock_response.iter_content.return_value = [b"test"]

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.get", return_value=mock_response) as mock_get:
            image_data, content_type = fetch_proxied_image(
                "https://example.com/image.jpg"
            )

    assert image_data == b"test"
    assert content_type == "image/jpeg"
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == "https://example.com/image.jpg"


def test_fetch_proxied_image_accepts_octet_stream_for_image_extension():
    register_proxy_urls_from_results(
        [{"properties": {"url": "https://example.com/image.jpg"}}]
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "application/octet-stream"}
    mock_response.iter_content.return_value = [b"test"]

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.get", return_value=mock_response):
            image_data, content_type = fetch_proxied_image(
                "https://example.com/image.jpg"
            )

    assert image_data == b"test"
    assert content_type == "application/octet-stream"


def test_fetch_proxied_image_rejects_non_image_content_type():
    register_proxy_urls_from_results(
        [{"properties": {"url": "https://example.com/page"}}]
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html></html>"]

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.get", return_value=mock_response):
            with pytest.raises(ProxyError, match="did not return an image"):
                fetch_proxied_image("https://example.com/page")


def test_fetch_proxied_image_rejects_oversized_image():
    register_proxy_urls_from_results(
        [{"properties": {"url": "https://example.com/big.jpg"}}]
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": str(16 * 1024 * 1024),
    }
    mock_response.iter_content.return_value = []

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.get", return_value=mock_response):
            with pytest.raises(ProxyError, match="too large") as exc_info:
                fetch_proxied_image("https://example.com/big.jpg")

    assert exc_info.value.status_code == 413


def test_fetch_proxied_image_timeout_raises():
    register_proxy_urls_from_results(
        [{"properties": {"url": "https://example.com/image.jpg"}}]
    )

    with patch("app.socket.getaddrinfo", return_value=_public_dns_result()):
        with patch("app.requests.get", side_effect=requests.Timeout("timed out")):
            with pytest.raises(ProxyError, match="timed out") as exc_info:
                fetch_proxied_image("https://example.com/image.jpg")

    assert exc_info.value.status_code == 504


def test_validate_safesearch_defaults_and_accepts_values():
    assert validate_safesearch(None) == "strict"
    assert validate_safesearch("off") == "off"
    assert validate_safesearch("STRICT") == "strict"


def test_validate_safesearch_rejects_invalid_value():
    with pytest.raises(ValidationError, match="safesearch"):
        validate_safesearch("moderate")


def test_validate_country_defaults_and_accepts_values():
    assert validate_country(None) == "US"
    assert validate_country("gb") == "GB"
    assert validate_country("all") == "ALL"


def test_validate_country_rejects_invalid_value():
    with pytest.raises(ValidationError, match="country"):
        validate_country("USA")


def test_validate_search_lang_defaults_and_accepts_values():
    assert validate_search_lang(None) == "en"
    assert validate_search_lang("ES") == "es"
    assert validate_search_lang("ja") == "jp"
    assert validate_search_lang("pt") == "pt-pt"
    assert validate_search_lang("pt-br") == "pt-br"


def test_validate_search_lang_rejects_invalid_value():
    with pytest.raises(ValidationError, match="search_lang"):
        validate_search_lang("e")


def test_validate_count_defaults_and_accepts_values():
    assert validate_count(None) == 50
    assert validate_count(200) == 200


def test_validate_count_rejects_invalid_value():
    with pytest.raises(ValidationError, match="count"):
        validate_count(0)


def test_validate_offset_defaults_and_accepts_values():
    assert validate_offset(None) == 0
    assert validate_offset(9) == 9


def test_validate_offset_rejects_invalid_value():
    with pytest.raises(ValidationError, match="offset"):
        validate_offset(10)


def test_max_offset_for_count_respects_brave_image_cap():
    assert max_offset_for_count(50) == 3
    assert max_offset_for_count(200) == 0
    assert max_offset_for_count(100) == 1


def test_build_search_response_has_more_when_count_can_grow():
    results = [{"properties": {"url": f"https://example.com/{i}.jpg"}} for i in range(50)]
    response = build_search_response(results, offset=0, count=50)

    assert response["has_more"] is True


def test_build_search_response_has_no_more_when_count_exhausted():
    results = [{"properties": {"url": f"https://example.com/{i}.jpg"}} for i in range(49)]
    response = build_search_response(results, offset=0, count=50)

    assert response["has_more"] is False


def test_build_search_response_has_more_when_using_offset_pages():
    results = [{"properties": {"url": f"https://example.com/{i}.jpg"}} for i in range(50)]
    response = build_search_response(results, offset=1, count=50)

    assert response["has_more"] is True
    assert response["offset"] == 1


def test_build_search_response_has_no_more_at_brave_cap():
    results = [{"properties": {"url": f"https://example.com/{i}.jpg"}} for i in range(200)]
    response = build_search_response(results, offset=0, count=200)

    assert response["has_more"] is False


def test_build_search_response_has_no_more_at_offset_cap():
    results = [{"properties": {"url": f"https://example.com/{i}.jpg"}} for i in range(50)]
    response = build_search_response(results, offset=3, count=50)

    assert response["has_more"] is False


def test_build_search_response_has_no_more_when_offset_page_is_empty():
    response = build_search_response([], offset=3, count=50)

    assert response["has_more"] is False
