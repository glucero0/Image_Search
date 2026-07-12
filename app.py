import ipaddress
import os
import socket
import time
from threading import Lock
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

load_dotenv()

base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, "templates")

app = Flask(__name__, template_folder=template_dir)
CORS(app)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/images/search"
MAX_QUERY_LENGTH = 400
REQUEST_TIMEOUT = (5, 30)
MAX_PROXY_BYTES = 15 * 1024 * 1024
ALLOWED_PROXY_TTL_SECONDS = 3600
ALLOWED_PROXY_URLS: dict[str, float] = {}
ALLOWED_PROXY_LOCK = Lock()
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "metadata.google.internal",
        "metadata.google",
    }
)
ALLOWED_SAFESEARCH = {"off", "strict"}
ALLOWED_COUNTRIES = frozenset(
    {
        "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "GR",
        "HK", "IN", "ID", "IT", "JP", "KR", "MY", "MX", "NL", "NZ", "NO", "CN",
        "PL", "PT", "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW", "TR", "GB",
        "US", "ALL",
    }
)
ALLOWED_SEARCH_LANGS = frozenset(
    {
        "ar", "eu", "bn", "bg", "ca", "zh-hans", "zh-hant", "hr", "cs", "da",
        "nl", "en", "en-gb", "et", "fi", "fr", "gl", "de", "el", "gu", "he",
        "hi", "hu", "is", "it", "jp", "kn", "ko", "lv", "lt", "ms", "ml", "mr",
        "nb", "pl", "pt-br", "pt-pt", "pa", "ro", "ru", "sr", "sk", "sl", "es",
        "sv", "ta", "te", "th", "tr", "uk", "vi",
    }
)
SEARCH_LANG_ALIASES = {
    "ja": "jp",
    "pt": "pt-pt",
    "zh": "zh-hans",
    "zh-cn": "zh-hans",
    "zh-tw": "zh-hant",
}
DEFAULT_SAFESEARCH = "strict"
DEFAULT_COUNTRY = "US"
DEFAULT_SEARCH_LANG = "en"
DEFAULT_COUNT = 50
MAX_COUNT = 200
MAX_BRAVE_IMAGES = 200
MAX_OFFSET = 9


def max_offset_for_count(count):
    if count < 1:
        return 0
    return min(MAX_OFFSET, max(0, (MAX_BRAVE_IMAGES - 1) // count))


class BraveAPIError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


class ProxyError(Exception):
    def __init__(self, message, status_code=400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ValidationError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


PLACEHOLDER_API_KEYS = {
    "",
    "your_brave_search_api_key_here",
}


def get_api_key():
    value = os.environ.get("BRAVE_API_KEY", "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def parse_brave_error(response):
    try:
        payload = response.json()
    except ValueError:
        return f"Brave API error: {response.status_code}"

    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("detail", "message", "code", "id"):
            if error.get(key):
                return str(error[key])
    if payload.get("message"):
        return str(payload["message"])
    return f"Brave API error: {response.status_code}"


def format_brave_422_error(response):
    detail = parse_brave_error(response)
    lowered = detail.lower()
    if any(term in lowered for term in ("plan", "subscription", "not in plan")):
        return (
            f"{detail} "
            "Image Search requires a Brave Search plan that includes images "
            "(not Autosuggest or Spellcheck only). "
            "Verify your API key at https://api-dashboard.search.brave.com/"
        )
    return detail


def validate_safesearch(value):
    if value is None:
        return DEFAULT_SAFESEARCH
    normalized = str(value).strip().lower()
    if normalized not in ALLOWED_SAFESEARCH:
        raise ValidationError("safesearch must be 'off' or 'strict'")
    return normalized


def validate_country(value):
    if value is None:
        return DEFAULT_COUNTRY
    normalized = str(value).strip().upper()
    if normalized not in ALLOWED_COUNTRIES:
        raise ValidationError(
            "country must be a Brave-supported 2-letter code or ALL"
        )
    return normalized


def validate_search_lang(value):
    if value is None:
        return DEFAULT_SEARCH_LANG
    normalized = str(value).strip().lower()
    normalized = SEARCH_LANG_ALIASES.get(normalized, normalized)
    if normalized not in ALLOWED_SEARCH_LANGS:
        raise ValidationError(
            "search_lang must be a Brave-supported language code "
            "(e.g. en, es, jp, pt-pt)"
        )
    return normalized


def clear_allowed_proxy_urls():
    with ALLOWED_PROXY_LOCK:
        ALLOWED_PROXY_URLS.clear()


def validate_count(value):
    if value is None:
        return DEFAULT_COUNT
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("count must be an integer between 1 and 200") from exc
    if count < 1 or count > MAX_COUNT:
        raise ValidationError("count must be an integer between 1 and 200")
    return count


def validate_offset(value):
    if value is None:
        return 0
    try:
        offset = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("offset must be an integer between 0 and 9") from exc
    if offset < 0 or offset > MAX_OFFSET:
        raise ValidationError("offset must be an integer between 0 and 9")
    return offset


def build_search_response(results, offset, count):
    page_limit = max_offset_for_count(count)
    if offset == 0:
        has_more = len(results) >= count and count < MAX_BRAVE_IMAGES
    else:
        has_more = len(results) > 0 and offset < page_limit
    return {
        "results": results,
        "offset": offset,
        "count": count,
        "has_more": has_more,
    }


def cleanup_expired_proxy_urls():
    now = time.time()
    with ALLOWED_PROXY_LOCK:
        expired = [
            url for url, expires_at in ALLOWED_PROXY_URLS.items() if expires_at <= now
        ]
        for url in expired:
            del ALLOWED_PROXY_URLS[url]


def register_proxy_urls_from_results(results):
    expires_at = time.time() + ALLOWED_PROXY_TTL_SECONDS
    with ALLOWED_PROXY_LOCK:
        for item in results:
            properties = item.get("properties") or {}
            image_url = properties.get("url")
            if image_url:
                ALLOWED_PROXY_URLS[image_url] = expires_at

            thumbnail = (item.get("thumbnail") or {}).get("src")
            if thumbnail:
                ALLOWED_PROXY_URLS[thumbnail] = expires_at


def get_authorized_proxy_url(requested_url):
    validate_proxy_url(requested_url)
    cleanup_expired_proxy_urls()
    with ALLOWED_PROXY_LOCK:
        expires_at = ALLOWED_PROXY_URLS.get(requested_url)
        if expires_at and expires_at > time.time():
            return requested_url
    raise ProxyError("Image URL is not authorized", 403)


def is_blocked_ip(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_proxy_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ProxyError("Invalid or disallowed image URL", 400)

    hostname = parsed.hostname
    if not hostname:
        raise ProxyError("Invalid or disallowed image URL", 400)

    lowered = hostname.lower().rstrip(".")
    if lowered in BLOCKED_HOSTNAMES:
        raise ProxyError("Invalid or disallowed image URL", 400)

    if is_blocked_ip(hostname):
        raise ProxyError("Invalid or disallowed image URL", 400)

    return parsed


def is_image_content_type(content_type, url):
    normalized = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if normalized.startswith("image/"):
        return True
    if normalized in {"application/octet-stream", "binary/octet-stream"}:
        path = urlparse(url).path.lower()
        return path.endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico")
        )
    return False


def resolve_public_ip(hostname):
    try:
        addrinfos = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise ProxyError("Could not resolve image host", 400) from exc

    if not addrinfos:
        raise ProxyError("Could not resolve image host", 400)

    for _, _, _, _, sockaddr in addrinfos:
        if is_blocked_ip(sockaddr[0]):
            raise ProxyError("Image host resolves to a disallowed address", 400)

    for _, _, _, _, sockaddr in addrinfos:
        ip = sockaddr[0]
        if not is_blocked_ip(ip):
            return ip

    raise ProxyError("Could not resolve image host", 400)


def is_safe_image_url(url):
    try:
        validate_proxy_url(url)
    except ProxyError:
        return False
    return True


def fetch_proxied_image(url, timeout=REQUEST_TIMEOUT):
    authorized_url = get_authorized_proxy_url(url)
    parsed = urlparse(authorized_url)
    resolve_public_ip(parsed.hostname)

    try:
        response = requests.get(
            authorized_url,
            timeout=timeout,
            stream=True,
            headers={
                "User-Agent": "ImageSearch/1.0",
                "Accept": "image/*,*/*",
            },
        )
    except requests.Timeout as exc:
        raise ProxyError("Image request timed out", 504) from exc
    except requests.RequestException as exc:
        raise ProxyError("Failed to fetch image", 502) from exc

    if response.status_code != 200:
        raise ProxyError(f"Image fetch failed: {response.status_code}", 502)

    content_type = response.headers.get("Content-Type", "application/octet-stream")
    if not is_image_content_type(content_type, authorized_url):
        raise ProxyError("URL did not return an image", 400)

    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_PROXY_BYTES:
        raise ProxyError("Image is too large", 413)

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_PROXY_BYTES:
            raise ProxyError("Image is too large", 413)
        chunks.append(chunk)

    if not chunks:
        raise ProxyError("Image response was empty", 502)

    return b"".join(chunks), content_type.split(";")[0]


def brave_image_search(
    query,
    api_key,
    *,
    safesearch=DEFAULT_SAFESEARCH,
    country=DEFAULT_COUNTRY,
    search_lang=DEFAULT_SEARCH_LANG,
    count=DEFAULT_COUNT,
    offset=0,
    timeout=REQUEST_TIMEOUT,
):
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": query,
        "safesearch": safesearch,
        "country": country,
        "search_lang": search_lang,
        "count": count,
        "offset": offset,
    }

    try:
        response = requests.get(
            BRAVE_API_URL, headers=headers, params=params, timeout=timeout
        )
    except requests.Timeout as exc:
        raise BraveAPIError("Search request timed out", 504) from exc
    except requests.RequestException as exc:
        raise BraveAPIError("Failed to reach Brave API", 502) from exc

    if response.status_code == 403:
        raise BraveAPIError(
            "Access Denied: Check your Brave API subscription.", 502
        )
    if response.status_code == 422:
        raise BraveAPIError(format_brave_422_error(response), 422)
    if response.status_code != 200:
        raise BraveAPIError(parse_brave_error(response), 502)

    try:
        data = response.json()
    except ValueError as exc:
        raise BraveAPIError("Invalid response from Brave API", 502) from exc

    return data.get("results", [])


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/proxy")
def proxy():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url query parameter is required"}), 400

    try:
        image_data, content_type = fetch_proxied_image(url)
    except ProxyError as exc:
        app.logger.warning("Proxy error while fetching image: %s", exc.message)
        return jsonify({"error": exc.message}), exc.status_code

    return Response(image_data, mimetype=content_type)


@app.route("/search", methods=["POST"])
def search():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Query is required"}), 400
    if len(query) > MAX_QUERY_LENGTH:
        return jsonify(
            {"error": f"Query is too long (max {MAX_QUERY_LENGTH} characters)"}
        ), 400

    try:
        safesearch = validate_safesearch(data.get("safesearch"))
        country = validate_country(data.get("country"))
        search_lang = validate_search_lang(data.get("search_lang"))
        count = validate_count(data.get("count"))
        offset = validate_offset(data.get("offset"))
    except ValidationError as exc:
        return jsonify({"error": exc.message}), 400

    page_limit = max_offset_for_count(count)
    if offset > page_limit:
        return jsonify(
            {
                "error": (
                    f"offset must be between 0 and {page_limit} "
                    f"when count is {count} (Brave returns up to {MAX_BRAVE_IMAGES} images)"
                )
            }
        ), 400

    api_key = get_api_key()
    if not api_key or api_key in PLACEHOLDER_API_KEYS:
        return jsonify(
            {
                "error": (
                    "Server API key not configured. Set BRAVE_API_KEY in .env "
                    "with a key from https://api-dashboard.search.brave.com/"
                )
            }
        ), 503

    try:
        results = brave_image_search(
            query,
            api_key,
            safesearch=safesearch,
            country=country,
            search_lang=search_lang,
            count=count,
            offset=offset,
        )
        register_proxy_urls_from_results(results)
        return jsonify(build_search_response(results, offset, count))
    except BraveAPIError as exc:
        return jsonify({"error": str(exc)}), exc.status_code


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, port=port)
