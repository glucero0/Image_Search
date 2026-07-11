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

Set `BRAVE_API_KEY` in your environment (or `.env` if you load it manually), then start the server:

```bash
# Windows PowerShell
$env:BRAVE_API_KEY="your_key_here"
python app.py
```

Open http://localhost:5000 in your browser.

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAVE_API_KEY` | *(required)* | Brave Search API subscription token |
| `FLASK_DEBUG` | `0` | Set to `1` to enable Flask debug mode |
| `PORT` | `5000` | Port for the development server |

## Test

```bash
pytest
```

## API

`POST /search`

Request body:

```json
{ "query": "black ferrari" }
```

Returns a JSON array of Brave image results, or `{ "error": "..." }` with an appropriate HTTP status code.
