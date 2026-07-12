# Image Search

A small Flask app that searches for images via the [Brave Image Search API](https://api-dashboard.search.brave.com/app/documentation/image-search/get-started) and displays them in a grid with optional bulk ZIP download.

## Setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements-dev.txt
   playwright install chromium
   ```

3. Copy `.env.example` to `.env` and set your Brave API key:

   ```bash
   copy .env.example .env
   ```

   Get an API key from the [Brave Search API dashboard](https://api-dashboard.search.brave.com/).

## Run

Set `BRAVE_API_KEY` in `.env`, then start the server:

```bash
python app.py
```

Open http://localhost:5000 in your browser.

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAVE_API_KEY` | *(required)* | Brave Search API subscription token |
| `FLASK_DEBUG` | `0` | Set to `1` to enable Flask debug mode |
| `PORT` | `5000` | Port for the development server |

## Features

- Image search with configurable **safe search**, **country**, and **language**
- Fetches up to **200 images** per search in one request (Brave’s per-query maximum)
- **Image titles** shown below each thumbnail
- **Image selection** with select all / deselect all
- Grid display with lightbox preview (press **Esc** to close, **Enter** to search)
- Bulk **ZIP download** of selected images via server-side **image proxy**, with download progress
- ZIP contains a **folder** named after the query; files are named from each image’s **title** plus a millisecond timestamp (e.g. `Red_Car1731234567890.jpg`)
- **Manifest export** to JSON or CSV (title, URL, source, dimensions)
- Duplicate image URLs are filtered from results

## Test

Unit tests:

```bash
pytest tests --ignore=tests/e2e
```

E2E smoke tests (requires Playwright browser):

```bash
playwright install chromium
pytest tests/e2e
```

All tests:

```bash
pytest
```

## API

### `POST /search`

Request body:

```json
{
  "query": "black ferrari",
  "safesearch": "strict",
  "country": "US",
  "search_lang": "en",
  "count": 200,
  "offset": 0
}
```

| Field | Required | Default | Values |
|-------|----------|---------|--------|
| `query` | yes | — | 1–400 characters |
| `safesearch` | no | `strict` | `off`, `strict` |
| `country` | no | `US` | Brave-supported 2-letter code or `ALL` |
| `search_lang` | no | `en` | Brave-supported code (e.g. `en`, `es`, `jp`, `pt-pt`); aliases like `ja` → `jp` |
| `count` | no | `50` | 1–200 (`200` is Brave’s per-request maximum; the UI always sends `200`) |
| `offset` | no | `0` | 0–9 page offset (capped by `count` and Brave’s 200-image limit); the UI always sends `0` |

Returns a JSON object:

```json
{
  "results": [],
  "offset": 0,
  "count": 200,
  "has_more": false
}
```

`has_more` indicates whether another page is available when using `offset` pagination via the API. The web UI does not paginate; it requests `count=200` once.

Or `{ "error": "..." }` with an appropriate HTTP status code.

### `GET /proxy?url=...`

Fetches an image server-side and returns the bytes. Used by ZIP download to work around browser CORS restrictions.

- Only image URLs returned by a recent `/search` on this server are authorized (including `properties.url` and `thumbnail.src`)
- Hostnames are resolved before fetch; private, loopback, and link-local addresses are blocked
- Outbound requests connect to the resolved public IP with TLS verified against the original hostname
- Responses are limited to 15 MB and must be an image content type (`image/*`, or `application/octet-stream` for common image extensions)

Returns the image bytes on success, or `{ "error": "..." }` on failure.

## CI

GitHub Actions runs unit tests and Playwright E2E smoke tests on push/PR. Dependabot keeps GitHub Actions dependencies updated.
