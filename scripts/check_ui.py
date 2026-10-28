"""Exercise real browser/API interactions against a running simulation server."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CAPSULE_TEST_URL", "http://127.0.0.1:8080")
OUTPUT = Path("docs/assets")
OUTPUT.mkdir(parents=True, exist_ok=True)
results = []

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"),
        headless=True,
        args=["--no-sandbox"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function(
        "document.querySelector('#connection').textContent === 'Сервер подключён'"
    )
    page.get_by_role("button", name="Включить Радио Дача", exact=True).first.click()
    page.wait_for_function("document.querySelector('#now-state').textContent.includes('В эфире')")
    # Tap the illuminated rim; center touch buttons remain separate controls.
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
    assert not page.request.get(BASE + "/api/v1/device").json()["lights"]["zones"]["front"][
        "enabled"
    ]
    page.reload(wait_until="networkidle")
    page.wait_for_function(
        "document.querySelector('#connection').textContent === 'Сервер подключён'"
    )
    page.locator('[data-zone="front"]').click()
    assert not page.locator("#light-enabled").is_checked()
    page.locator('[data-tab="home"]').click()
    page.locator("#command").fill("Маруся, громкость 40 процентов")
    page.locator("#command-form button").click()
    page.wait_for_function("document.querySelector('#volume-value').textContent === '40%'")
    page.locator('[data-tab="settings"]').click()
    page.locator("#mic-muted").check()
    page.wait_for_timeout(350)
    assert page.request.get(BASE + "/api/v1/device").json()["preferences"]["microphone_muted"]
    page.locator("#mic-muted").uncheck()
    page.locator('[data-tab="radio"]').click()
    favorite = page.locator("#all-stations .favorite-button").first
    if not favorite.evaluate("el => el.classList.contains('saved')"):
        favorite.click()
    page.wait_for_selector("#favorites .station-card")
    # Return preview to an attractive, explicit simulation state.
    page.locator('[data-tab="home"]').click()
    page.locator('[data-preset="night"]').click()
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUTPUT / "menu-desktop.png"), full_page=True)
    page.locator('[data-tab="lights"]').click()
    assert page.locator("#send-top").is_hidden()
    assert page.locator("#send-clock").is_hidden()
    page.screenshot(path=str(OUTPUT / "menu-lights.png"), full_page=True)
    for width in [320, 360, 390, 600, 768, 1024, 1440, 1920]:
        page.set_viewport_size({"width": width, "height": 900})
        for name in ["home", "radio", "lights", "settings"]:
            page.locator(f'[data-tab="{name}"]').click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                width,
                name,
            )
            results.append({"width": width, "tab": name, "overflow": False})
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('[data-tab="home"]').click()
    page.screenshot(path=str(OUTPUT / "menu-mobile.png"), full_page=True)
    assert not errors, errors
    browser.close()

Path("docs/qa/browser-results.json").write_text(
    json.dumps(
        {
            "checks": results,
            "javascript_errors": errors,
            "interactions": [
                "play_station",
                "top_light_color",
                "front_light_off",
                "reload_persistence",
                "local_volume_command",
                "microphone_mute",
                "favorites",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
)
print(f"Browser: {len(results)} layout checks and 7 API interactions passed")
