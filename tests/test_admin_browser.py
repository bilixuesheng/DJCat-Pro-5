"""The shared admin.js interactions, driven in a real browser.

Every request goes through the Flask test client and comes back with its real
headers, so the admin CSP applies: a page that only works with inline script
fails here the way it fails in production.

Skipped where Playwright or a Chromium build is not available; the release CI
does not install either, so this guards local and cloud runs only.
"""

import os
import re
from contextlib import closing
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

CHROMIUM = os.environ.get("DJCAT_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM).exists(), reason="no Chromium build for Playwright"
)

from server import ai_markdown  # noqa: E402
from tests import test_ai_admin  # noqa: E402

BASE = "https://dash.djcatpro.top"
FORWARDED_HEADERS = ("content-type", "x-requested-with", "accept")


class _Fixture(test_ai_admin.AIAdminTest):
    """Borrow the admin fixture without collecting AIAdminTest's own tests."""

    __test__ = False


@pytest.fixture
def admin():
    fixture = _Fixture("setUp")
    fixture.setUp()
    client = fixture.client
    login = client.get("/admin/login", base_url=BASE)
    token = re.search(rb'name="csrf_token" value="([^"]+)"', login.data)
    client.post(
        "/admin/login",
        base_url=BASE,
        data={
            "csrf_token": token.group(1).decode(),
            "username": "admin",
            "password": "secret",
        },
    )

    def handle(route):
        request = route.request
        if not request.url.startswith(BASE):
            return route.fulfill(status=204, body="")
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in FORWARDED_HEADERS
        }
        response = client.open(
            request.url[len(BASE):],
            base_url=BASE,
            method=request.method,
            data=request.post_data_buffer,
            headers=headers,
        )
        return route.fulfill(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.data,
        )

    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROMIUM)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/*", handle)
        yield page
        browser.close()
    for cleanup in reversed(fixture._cleanups):
        cleanup[0](*cleanup[1], **cleanup[2])


def _open(page, path):
    page.goto(BASE + path)
    page.wait_for_load_state("networkidle")


def _rows(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('tbody > tr[data-sort-id]')]"
        ".map((row) => Number(row.dataset.sortId))"
    )


def _savedOrder():
    return [example["id"] for example in ai_markdown._allPromptExamples()]


def _confirm(page):
    page.locator(".confirm-dialog .button-danger").click()


def _toast(page, text):
    page.locator(".toast", has_text=text).wait_for()


def testArrowKeysReorderExamples(admin):
    _open(admin, "/admin/ai/markdown/examples/")
    before = _rows(admin)
    admin.locator("tr[data-sort-id] .drag-handle").first.focus()
    admin.keyboard.press("ArrowDown")
    _toast(admin, "排序已保存")

    assert _rows(admin) == [before[1], before[0], *before[2:]]
    assert _rows(admin) == _savedOrder()


def testDraggingReordersExamples(admin):
    _open(admin, "/admin/ai/markdown/examples/")
    before = _rows(admin)
    rows = admin.locator("tr[data-sort-id]")
    handle = rows.first.locator(".drag-handle").bounding_box()
    last = rows.last.bounding_box()
    admin.mouse.move(handle["x"] + 5, handle["y"] + 5)
    admin.mouse.down()
    target = last["y"] + last["height"] - 2
    for step in range(1, 16):
        admin.mouse.move(
            handle["x"] + 5, handle["y"] + (target - handle["y"]) * step / 15
        )
        admin.wait_for_timeout(20)
    admin.mouse.up()
    _toast(admin, "排序已保存")

    assert _rows(admin) == [*before[1:], before[0]]
    assert _rows(admin) == _savedOrder()


def testEditingAnExampleOpensItsOwnPageAndReturnsToTheList(admin):
    _open(admin, "/admin/ai/markdown/examples/")
    first = _rows(admin)[0]
    admin.locator(f"tr[data-sort-id='{first}'] a", has_text="编辑").click()
    admin.wait_for_url(f"**/examples/{first}/edit")
    admin.locator("textarea[name=output_content]").fill("**【语文】**\n- 改过了")
    admin.locator("button[type=submit]", has_text="保存").click()

    admin.wait_for_url("**/admin/ai/markdown/examples/")
    _toast(admin, "示例已更新")
    assert "改过了" in admin.locator(f"tr[data-sort-id='{first}']").inner_text()


def testNewExampleIsAppendedLast(admin):
    _open(admin, "/admin/ai/markdown/examples/")
    before = _rows(admin)
    admin.locator("a", has_text="新增示例").click()
    admin.wait_for_url("**/examples/new")
    admin.locator("textarea[name=input_content]").fill("化学做练习册12页")
    admin.locator("textarea[name=output_content]").fill("**【化学】**\n- 练习册12页")
    admin.locator("button[type=submit]", has_text="保存").click()

    admin.wait_for_url("**/admin/ai/markdown/examples/")
    _toast(admin, "示例已加入")
    after = _rows(admin)
    assert after[:-1] == before
    assert "化学做练习册12页" in admin.locator("tbody tr").last.inner_text()


def testARejectedExampleStaysOnTheFormWithItsText(admin):
    _open(admin, "/admin/ai/markdown/examples/new")
    admin.locator("textarea[name=input_content]").fill("只有输入")
    admin.locator("textarea[name=output_content]").fill("   ")
    admin.locator("button[type=submit]", has_text="保存").click()

    _toast(admin, "输入和输出内容不能为空")
    assert admin.url.endswith("/examples/new")
    assert admin.locator("textarea[name=input_content]").input_value() == "只有输入"


def testResettingExamplesReplacesTheTableInPlace(admin):
    _open(admin, "/admin/ai/markdown/examples/")
    admin.evaluate("() => { window.__samePage = true; }")
    admin.locator("tbody tr").first.locator("button", has_text="删除").click()
    _confirm(admin)
    _toast(admin, "示例已删除")
    assert admin.locator("[data-item-count]").inner_text() == "3"

    admin.locator("button", has_text="恢复默认示例").click()
    _confirm(admin)
    _toast(admin, "已恢复默认示例")

    assert admin.evaluate("() => window.__samePage") is True
    assert _rows(admin) == _savedOrder()
    assert len(_rows(admin)) == len(ai_markdown.DEFAULT_EXAMPLES)
    assert admin.locator("[data-item-count]").inner_text() == "4"
    # 换进来的新行照样能排序（原始顺序快照跟着更新）和删除。
    admin.locator("tr[data-sort-id] .drag-handle").first.focus()
    admin.keyboard.press("ArrowDown")
    _toast(admin, "排序已保存")
    assert _rows(admin) == _savedOrder()
    admin.locator("tbody tr").last.locator("button", has_text="删除").click()
    _confirm(admin)
    _toast(admin, "示例已删除")
    assert len(_savedOrder()) == len(ai_markdown.DEFAULT_EXAMPLES) - 1
    assert admin.evaluate("() => window.__samePage") is True


def testResettingThePromptFillsTheDefaultInPlace(admin):
    ai_markdown._saveSystemPrompt(ai_markdown._LEGACY_SYSTEM_PROMPT)
    _open(admin, "/admin/ai/markdown/prompt")
    admin.evaluate("() => { window.__samePage = true; }")
    admin.locator("button", has_text="恢复默认提示词").click()
    _confirm(admin)
    _toast(admin, "已恢复默认提示词")

    assert admin.evaluate("() => window.__samePage") is True
    assert (
        admin.locator("textarea[name=system_prompt]").input_value()
        == ai_markdown.DEFAULT_PROMPT_TEMPLATE
    )
    assert ai_markdown._setting("system_prompt") is None


def testAddingALogAsAnExampleReturnsToTheLogList(admin):
    ai_markdown._saveConversionLog("a" * 64, "英语做97页", "- 做97页", "")
    with closing(ai_markdown._connect()) as database:
        logId = database.execute("SELECT MAX(id) FROM conversion_logs").fetchone()[0]
    _open(admin, f"/admin/ai/markdown/logs/{logId}/add")
    admin.locator("button[type=submit]", has_text="加入提示词示例").click()

    admin.wait_for_url("**/admin/ai/markdown/logs/")
    _toast(admin, "示例已加入提示词")
    assert ai_markdown._getConversionLog(logId)["status"] == "approved"


def testQuotaDialogSetsAndRestoresTheOverrideInPlace(admin):
    client = ai_markdown.app.test_client()
    for machine in ("a", "b"):
        client.post("/ai/markdown/register", json={"machine_id": machine * 64})
    machineId = ai_markdown._machineId("a" * 64)
    ai_markdown._claimRequest(machineId, 3, ai_markdown._today(), 15)
    _open(admin, "/admin/ai/markdown/machines/")
    admin.evaluate("() => { window.__samePage = true; }")
    row = admin.locator("[data-replace='machine-DJ-000001']")
    dialog = admin.locator("[data-quota-dialog]")
    field = dialog.locator("input[name=daily_limit]")

    row.locator("button", has_text="设置额度").click()
    assert dialog.is_visible()
    assert dialog.locator("[data-quota-machine]").inner_text() == "DJ-000001"
    assert dialog.locator("[data-quota-restore]").is_hidden()
    dialog.locator("button", has_text="保存").click()
    assert dialog.is_visible()  # 空着不能保存
    field.fill("40")
    dialog.locator("button", has_text="保存").click()
    _toast(admin, "专属额度已设为每天 40 点")

    assert dialog.is_hidden()
    assert "37 / 40" in row.inner_text()
    assert "专属" in row.inner_text()
    assert ai_markdown._dailyQuota(machineId) == 40
    # 原按钮随整行换掉，焦点交给新行里的同一个按钮。
    assert admin.evaluate("() => document.activeElement.dataset.machineCode") == "DJ-000001"

    # 重置今日额度按这一行自己的上限回满，别的行按默认额度。
    row.locator("button", has_text="重置额度").click()
    _confirm(admin)
    _toast(admin, "机器额度已重置")
    assert "40 / 40" in row.inner_text()
    admin.locator("button", has_text="重置全部今日额度").click()
    _confirm(admin)
    _toast(admin, "所有机器今日额度已重置")
    assert "15 / 15" in admin.locator("[data-replace='machine-DJ-000002']").inner_text()
    assert "40 / 40" in row.inner_text()

    row.locator("button", has_text="设置额度").click()
    assert field.input_value() == "40"
    field.fill("")
    dialog.locator("button", has_text="恢复默认").click()
    _toast(admin, "已恢复默认额度")

    assert "15 / 15" in row.inner_text()
    assert "专属" not in row.inner_text()
    assert ai_markdown._dailyQuota(machineId) == 15
    assert admin.evaluate("() => window.__samePage") is True
