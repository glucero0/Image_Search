import os
import threading
import time
from unittest.mock import patch

import pytest
from playwright.sync_api import Page, expect

from app import app

E2E_IMAGE_ONE = (
    "data:image/gif;base64,"
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
E2E_IMAGE_TWO = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVQYGWNgYGAAAAAEAAH//wOxAAAAAABJRU5ErkJggg=="
)
E2E_RESULTS = [
    {
        "title": "Example image",
        "properties": {
            "url": E2E_IMAGE_ONE,
            "width": 800,
            "height": 600,
        },
    },
    {
        "title": "Second image",
        "properties": {
            "url": E2E_IMAGE_TWO,
        },
    },
]


@pytest.fixture(scope="module")
def server_url():
    os.environ["BRAVE_API_KEY"] = "test-api-key"

    def mock_search(*args, **kwargs):
        return E2E_RESULTS

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

    expect(page.locator(".img-card")).to_have_count(2)
    page.locator(".img-card img").first.click()

    expect(page.locator("#imageModal")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#imageModal")).to_be_hidden()
