import ipaddress
import os
import socket
from urllib.parse import urlparse, urlunparse

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS
from requests.adapters import HTTPAdapter

load_dotenv()

ALLOWED_PROXY_HOSTS = {
    "imgs.search.brave.com",
}

base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, "templates")

app = Flask(__name__, template_folder=template_dir)
CORS(app)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/images/search"
MAX_QUERY_LENGTH = 400
REQUEST_TIMEOUT = (5, 30)
MAX_PROXY_BYTES = 15 * 1024 * 1024
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
DEFAULT_SAFESEARCH = "strict"
DEFAULT_COUNTRY = "US"
DEFAULT_SEARCH_LANG = "en"


class BraveAPIError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


class ProxyError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


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


def validate_safesearch(value):
    if value is None:
        return DEFAULT_SAFESEARCH
    normalized = str(value).strip().lower()
    if normalized not in ALLOWED_SAFESEARCH:
        raise ValueError("safesearch must be 'off' or 'strict'")
    return normalized


def validate_country(value):
    if value is None:
        return DEFAULT_COUNTRY
    normalized = str(value).strip().upper()
    if normalized == "ALL":
        return normalized
    if len(normalized) != 2 or not normalized.isalpha():
        raise ValueError("country must be a 2-letter code or ALL")
    return normalized


def validate_search_lang(value):
    if value is None:
        return DEFAULT_SEARCH_LANG
    normalized = str(value).strip().lower()
    if len(normalized) < 2 or not normalized.isalpha():
        raise ValueError("search_lang must be a 2+ letter language code")
    return normalized


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


class PinningHTTPAdapter(HTTPAdapter):
    def __init__(self, hostname, pinned_ip):
        self.hostname = hostname
        self.pinned_ip = pinned_ip
        super().__init__()

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        parsed = urlparse(request.url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        netloc = str(self.pinned_ip)
        if port not in (80, 443):
            netloc = f"{netloc}:{port}"

        request.url = urlunparse(
            (parsed.scheme, netloc, path, "", "", "")
        )
        request.headers["Host"] = self.hostname
        return super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


def is_safe_image_url(url):
    try:
        validate_proxy_url(url)
    except ProxyError:
        return False
    return True


def fetch_proxied_image(url, timeout=REQUEST_TIMEOUT):
    parsed = validate_proxy_url(url)
    if parsed.hostname not in ALLOWED_PROXY_HOSTS:
        raise ProxyError("URL host is not allowed", 400)

    pinned_ip = resolve_public_ip(parsed.hostname)
    safe_url = urlunparse(parsed)

    session = requests.Session()
    adapter = PinningHTTPAdapter(parsed.hostname, pinned_ip)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        response = session.get(
            safe_url,
            timeout=timeout,
            stream=True,
            headers={"User-Agent": "ImageSearch/1.0"},
        )
    except requests.Timeout as exc:
        raise ProxyError("Image request timed out", 504) from exc
    except requests.RequestException as exc:
        raise ProxyError("Failed to fetch image", 502) from exc

    if response.status_code != 200:
        raise ProxyError(f"Image fetch failed: {response.status_code}", 502)

    content_type = response.headers.get("Content-Type", "application/octet-stream")
    if not content_type.startswith("image/"):
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
        "count": 150,
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
        raise BraveAPIError(
            f"{parse_brave_error(response)} "
            "Image Search requires a Brave Search plan that includes images "
            "(not Autosuggest or Spellcheck only). "
            "Verify your API key at https://api-dashboard.search.brave.com/",
            422,
        )
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
        app.logger.warning("Proxy error while fetching image: %s", exc)
        return jsonify({"error": "Unable to fetch the requested image"}), exc.status_code

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
    except ValueError:
        return jsonify({"error": "Invalid request parameters"}), 400

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
        )
        return jsonify(results)
    except BraveAPIError as exc:
        return jsonify({"error": str(exc)}), exc.status_code


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, port=port)
