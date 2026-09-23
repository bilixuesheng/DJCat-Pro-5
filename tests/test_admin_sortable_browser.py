"""The shared sortable table in admin.js, driven in a real browser.

Skipped where Playwright or a Chromium build is not available; the release CI
does not install either, so this guards local and cloud runs only.
"""

import os
import re
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

CHROMIUM = os.environ.get("DJCAT_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM).exists(), reason="no Chromium build for Playwright"
)

from tests import test_ai_admin  # noqa: E402

BASE = "https://dash.djcatpro.top"
STATIC = Path(__file__).resolve().parents[1] / "server"


class _Fixture(test_ai_admin.AIAdminTest):
    """Borrow the admin fixture without collecting AIAdminTest's own tests."""

    __test__ = False


@pytest.fixture
def examplesPage():
    fixture = _Fixture("setUp")
    fixture.setUp()
    client = fixture.client
    token = lambda response: re.search(  # noqa: E731
        rb'name="csrf_token" value="([^"]+)"', response.data
    ).group(1).decode()
    login = client.get("/admin/login", base_url=BASE)
    client.post(
        "/admin/login",
        base_url=BASE,
        data={"csrf_token": token(login), "username": "admin", "password": "secret"},
    )
    html = client.get("/admin/ai/markdown/examples/", base_url=BASE).get_data(
        as_text=True
    )

    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROMIUM)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        def handle(route):
            url = route.request.url
            if "/static/" in url:
                path = STATIC / url.split(BASE + "/", 1)[1]
                kind = {".css": "text/css", ".js": "application/javascript"}.get(
                    path.suffix, "image/png"
                )
                return route.fulfill(body=path.read_bytes(), content_type=kind)
            if url.endswith("/admin/ai/markdown/examples/reorder"):
                response = client.post(
                    "/admin/ai/markdown/examples/reorder",
                    base_url=BASE,
                    data=route.request.post_data_buffer,
                    content_type=route.request.headers["content-type"],
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                return route.fulfill(
                    status=response.status_code,
                    body=response.data,
                    content_type="application/json",
                )
            if url.rstrip("/") == f"{BASE}/admin/ai/markdown/examples":
                return route.fulfill(body=html, content_type="text/html")
            return route.fulfill(status=204, body="")

        page.route("**/*", handle)
        page.goto(f"{BASE}/admin/ai/markdown/examples/")
        page.wait_for_load_state("networkidle")
        yield page
        browser.close()
    for cleanup in reversed(fixture._cleanups):
        cleanup[0](*cleanup[1], **cleanup[2])


def _rows(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('tbody > tr')].map((row) =>
            row.dataset.sortId ? `S${row.dataset.sortId}` : `e${row.dataset.sortFollows}`)"""
    )


def _paired(rows):
    return len(rows) % 2 == 0 and all(
        rows[index + 1] == "e" + rows[index][1:] for index in range(0, len(rows), 2)
    )


def _savedOrder():
    from server import ai_markdown

    return [f"S{example['id']}" for example in ai_markdown._allPromptExamples()]


def testArrowKeysMovePastTheInlineEditRow(examplesPage):
    before = _rows(examplesPage)[::2]
    examplesPage.locator("tr[data-sort-id] .drag-handle").first.focus()
    examplesPage.keyboard.press("ArrowDown")
    examplesPage.wait_for_timeout(300)

    rows = _rows(examplesPage)
    assert rows[::2] == [before[1], before[0], *before[2:]]
    assert _paired(rows)
    assert rows[::2] == _savedOrder()


def testDraggingKeepsEachEditRowUnderItsOwnExample(examplesPage):
    rows = examplesPage.locator("tr[data-sort-id]")
    handle = rows.first.locator(".drag-handle").bounding_box()
    last = rows.last.bounding_box()
    examplesPage.mouse.move(handle["x"] + 5, handle["y"] + 5)
    examplesPage.mouse.down()
    target = last["y"] + last["height"] - 2
    for step in range(1, 16):
        examplesPage.mouse.move(
            handle["x"] + 5, handle["y"] + (target - handle["y"]) * step / 15
        )
        examplesPage.wait_for_timeout(20)
    examplesPage.mouse.up()
    examplesPage.wait_for_timeout(400)

    after = _rows(examplesPage)
    assert _paired(after)
    assert after[::2] == _savedOrder()
