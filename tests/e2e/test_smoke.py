import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from playwright.sync_api import Page, expect

from app import app

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "brave_response.json"


@pytest.fixture(scope="module")
def server_url():
    os.environ["BRAVE_API_KEY"] = "test-api-key"
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def mock_search(*args, **kwargs):
        offset = kwargs.get("offset", 0)
        if offset == 0:
            return fixture["results"]
        return []

    app.config["TESTING"] = True
    with patch("app.brave_image_search", side_effect=mock_search):
        thread = threading.Thread(
            target=lambda: app.run(port=5055, use_reloader=False, threaded=True),
            daemon=True,
        )
        thread.start()
        time.sleep(1)
        yield "http://127.0.0.1:5055"


@pytest.fixture
def page(page: Page, server_url):
    page.goto(server_url)
    return page


def test_homepage_renders_search_controls(page: Page):
    expect(page).to_have_title("Image Search")
    expect(page.get_by_label("Search Query")).to_be_visible()
    expect(page.get_by_role("button", name="Search")).to_be_visible()


def test_search_displays_results(page: Page):
    page.get_by_label("Search Query").fill("black ferrari")
    page.get_by_role("button", name="Search").click()

    expect(page.locator(".img-card")).to_have_count(2)
    expect(page.get_by_text("Showing 2 images")).to_be_visible()
    expect(page.locator(".img-card-title").first).to_have_text("Example image")
    expect(page.get_by_role("button", name="Save Selected to Zip")).to_be_visible()


def test_escape_closes_modal(page: Page):
    page.get_by_label("Search Query").fill("black ferrari")
    page.get_by_role("button", name="Search").click()
    page.locator(".img-card img").first.click()

    expect(page.locator("#imageModal")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#imageModal")).to_be_hidden()
