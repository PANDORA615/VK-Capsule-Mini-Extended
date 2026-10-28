"""Exercise the actual assistant menu and API against a running local server."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CAPSULE_TEST_URL", "http://127.0.0.1:8080")
OUTPUT = Path("docs/assets")
OUTPUT.mkdir(parents=True, exist_ok=True)
checks = []
interactions = [
    "five_case_colors",
    "independent_light_zones",
    "reload_persistence",
    "general_question_without_prefix",
    "reply_volume",
    "optional_prefix",
    "microphone_mute",
    "stop_answer",
    "installation_choices",
]
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"),
        headless=True,
        args=["--no-sandbox"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function(
        "document.querySelector('#connection').textContent === 'Сервер подключён'"
    )
    original = page.request.get(BASE + "/api/v1/device").json()["lights"]
    for color in ["light_gray", "green", "terracotta", "dark_gray", "blue"]:
        page.locator("#case-color").select_option(color)
        page.wait_for_function(
            "color => document.documentElement.dataset.case === color", arg=color
        )
        assert (
            page.request.get(BASE + "/api/v1/device").json()["preferences"]["case_color"] == color
        )
    assert page.request.get(BASE + "/api/v1/device").json()["lights"] == original
    page.locator("#top-hotspot").click(position={"x": 100, "y": 10})
    page.wait_for_selector("#tab-lights.active")
    page.locator('[data-color="#ffb66e"]').click()
    page.wait_for_function(
        "document.querySelector('#light-save-status').textContent === 'Сохранено'"
    )
    assert (
        page.request.get(BASE + "/api/v1/device").json()["lights"]["zones"]["top"]["color"]
        == "#ffb66e"
    )
    page.locator('[data-zone="front"]').click()
    page.locator("#light-enabled").uncheck()
    page.wait_for_function(
        "document.querySelector('#light-save-status').textContent === 'Сохранено'"
    )
    page.reload(wait_until="networkidle")
    page.wait_for_function(
        "document.querySelector('#connection').textContent === 'Сервер подключён'"
    )
    page.locator('[data-zone="front"]').click()
    assert not page.locator("#light-enabled").is_checked()
    page.locator('[data-tab="home"]').click()
    page.locator("#command").fill("Объясни почему небо голубое")
    with page.expect_response(lambda r: r.url.endswith("/api/v1/commands")) as response:
        page.locator("#command-form button").click()
    assert response.value.status == 200 and not response.value.json()["local"]
    page.locator("#command").fill("громкость 40 процентов")
    page.locator("#command-form button").click()
    page.wait_for_function("document.querySelector('#volume-value').textContent === '40%'")
    assert page.locator("#reply-audio").evaluate("el => el.volume") == 0.4
    page.locator("#stop-answer").click()
    assert page.locator("#reply-audio").evaluate("el => el.paused")
    page.locator('[data-tab="settings"]').click()
    page.locator("#wake-word").fill("")
    with page.expect_response(lambda r: r.url.endswith("/api/v1/preferences")):
        page.locator("#save-wake").click()
    assert page.request.get(BASE + "/api/v1/device").json()["preferences"]["wake_word"] == ""
    page.locator("#mic-muted").check()
    page.wait_for_timeout(350)
    assert page.request.get(BASE + "/api/v1/device").json()["preferences"]["microphone_muted"]
    page.locator("#mic-muted").uncheck()
    page.locator('[data-tab="setup"]').click()
    assert page.locator(".install-card").count() == 4
    assert page.locator(".install-card a[href]").count() == 4
    page.locator('[data-tab="home"]').click()
    page.locator('[data-preset="cozy"]').click()
    page.wait_for_timeout(500)
    page.locator("#command").fill("")
    page.wait_for_function("!document.querySelector('#toast').classList.contains('visible')")
    page.screenshot(path=str(OUTPUT / "menu-desktop.png"), full_page=True)
    page.locator('[data-tab="lights"]').click()
    assert page.locator("#send-top").is_hidden()
    page.screenshot(path=str(OUTPUT / "menu-lights.png"), full_page=True)
    for width in [320, 360, 390, 600, 768, 1024, 1440, 1920]:
        page.set_viewport_size({"width": width, "height": 900})
        for name in ["home", "setup", "lights", "settings"]:
            page.locator(f'[data-tab="{name}"]').click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                width,
                name,
            )
            checks.append({"width": width, "tab": name, "overflow": False})
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('[data-tab="home"]').click()
    page.screenshot(path=str(OUTPUT / "menu-mobile.png"), full_page=True)
    assert not errors, errors
    browser.close()
Path("docs/qa/browser-results.json").write_text(
    json.dumps(
        {"checks": checks, "javascript_errors": errors, "interactions": interactions},
        ensure_ascii=False,
        indent=2,
    )
)
print(f"Browser: {len(checks)} layout checks and {len(interactions)} interaction scenarios passed")
