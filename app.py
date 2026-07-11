import os

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

load_dotenv()

base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, "templates")

app = Flask(__name__, template_folder=template_dir)
CORS(app)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/images/search"
MAX_QUERY_LENGTH = 400
REQUEST_TIMEOUT = (5, 30)


class BraveAPIError(Exception):
    def __init__(self, message, status_code=502):
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


def brave_image_search(query, api_key, timeout=REQUEST_TIMEOUT):
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": query,
        "safesearch": "off",
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
        results = brave_image_search(query, api_key)
        return jsonify(results)
    except BraveAPIError as exc:
        return jsonify({"error": str(exc)}), exc.status_code


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, port=port)
