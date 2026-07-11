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
- Grid display with lightbox preview
- Bulk ZIP download via a server-side **image proxy** (avoids browser CORS failures)

## Test

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
  "search_lang": "en"
}
```

| Field | Required | Default | Values |
|-------|----------|---------|--------|
| `query` | yes | — | 1–400 characters |
| `safesearch` | no | `strict` | `off`, `strict` |
| `country` | no | `US` | 2-letter code or `ALL` |
| `search_lang` | no | `en` | 2+ letter language code |

Returns a JSON array of Brave image results, or `{ "error": "..." }` with an appropriate HTTP status code.

### `GET /proxy?url=...`

Fetches an image server-side and returns the bytes. Used by ZIP download to work around browser CORS restrictions.

- Only image URLs returned by a recent `/search` on this server are authorized
- Hostnames are resolved before fetch; private, loopback, and link-local addresses are blocked
- Outbound requests use a pinned public IP and reconstructed request URL instead of the raw client input
- Responses are limited to 15 MB and must have an `image/*` content type

Returns the image bytes on success, or `{ "error": "..." }` on failure.
