"""The page in a real browser (Chromium, via Playwright): accessibility, zoom and rotation."""

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect, sync_playwright

from scripts.fixtures import FIXTURES_ROOT

pytestmark = pytest.mark.e2e

OLD_TOM = FIXTURES_ROOT / "synthetic" / "old-tom" / "label.png"
FORM = {
    "#brand_name": "OLD TOM DISTILLERY",
    "#class_type": "Kentucky Straight Bourbon Whiskey",
    "#alcohol_content": "45% Alc./Vol. (90 Proof)",
    "#net_contents": "750 mL",
    "#bottler": "Old Tom Distillery, Louisville, Kentucky",
}


@pytest.fixture
def page(live_server: str) -> Page:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(base_url=live_server)
        yield context.new_page()
        browser.close()


def results_page(page: Page) -> Page:
    page.goto("/")
    page.set_input_files("#images", OLD_TOM)
    for selector, value in FORM.items():
        page.fill(selector, value)
    page.click("button[type=submit]")
    expect(page.locator(".verdict")).to_be_visible()
    return page


def no_violations(page: Page) -> None:
    results = Axe().run(page)
    assert results.violations_count == 0, results.generate_report()


# ---- accessibility (axe-core) ----


def test_the_empty_form_has_no_accessibility_violations(page: Page) -> None:
    page.goto("/")

    no_violations(page)


def test_the_form_with_errors_has_no_accessibility_violations(page: Page) -> None:
    page.goto("/")
    page.set_input_files("#images", OLD_TOM)
    page.click("button[type=submit]")
    expect(page.locator(".error-summary")).to_be_visible()

    no_violations(page)


def test_a_results_page_has_no_accessibility_violations(page: Page) -> None:
    no_violations(results_page(page))


# ---- zoom and rotation ----


def test_a_result_zooms_to_its_spot_on_the_label(page: Page) -> None:
    results_page(page)

    page.locator("button.zoom").first.click()

    dialog = page.locator("dialog.zoom-view")
    expect(dialog).to_be_visible()
    expect(dialog.locator("h2")).to_contain_text("Brand")
    assert page.evaluate("document.querySelector('.zoom-canvas').width") > 0
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


def test_sideways_text_is_turned_upright_in_the_zoom(page: Page) -> None:
    results_page(page)

    page.locator("button.zoom[data-name='Government warning']").click()

    sideways = page.evaluate(
        "(() => { const c = document.querySelector('.zoom-canvas');"
        " return [c.dataset.sideways, c.width, c.height]; })()"
    )
    assert sideways[0] == "true"
    assert sideways[1] > sideways[2]  # a tall column of text, turned to read across


def test_each_image_turns_a_quarter_at_a_time(page: Page) -> None:
    results_page(page)
    frame = page.locator(".image-frame").first

    page.locator("button.rotate[data-turn='90']").first.click()
    expect(frame).to_have_class("image-frame turn-90")
    page.locator("button.rotate[data-turn='90']").first.click()
    expect(frame).to_have_class("image-frame turn-180")
    page.locator("button.rotate[data-turn='-90']").first.click()
    expect(frame).to_have_class("image-frame turn-90")


# ---- keyboard, quick checks and samples ----


def test_every_control_works_by_keyboard(page: Page) -> None:
    results_page(page)

    page.locator("button.zoom").first.focus()
    page.keyboard.press("Enter")
    expect(page.locator("dialog.zoom-view")).to_be_visible()
    page.keyboard.press("Escape")
    page.goto("/")
    reached = set()
    for _ in range(25):
        page.keyboard.press("Tab")
        reached.add(
            page.evaluate("document.activeElement.id || document.activeElement.textContent")
        )
    assert {"images", "sample", "brand_name", "bottler", "imported"} <= reached
    assert "Check label" in reached


def test_too_many_files_are_caught_before_uploading(page: Page, tmp_path: object) -> None:
    page.goto("/")
    page.set_input_files("#images", [OLD_TOM] * 7)
    page.click("button[type=submit]")

    expect(page.locator(".client-error")).to_contain_text("at most 6 images")
    assert page.url.endswith("/")  # still on the form: nothing was sent


def test_choosing_a_sample_fills_the_form(page: Page) -> None:
    page.goto("/")

    page.select_option("#sample", "old-tom")

    expect(page.locator("#brand_name")).to_have_value("OLD TOM DISTILLERY")
