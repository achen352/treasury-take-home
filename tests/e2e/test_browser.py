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
    # The results page is large (its images are inline), so wait for the deferred script too.
    page.wait_for_load_state("load")
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


# ---- a friendlier page ----


def test_chosen_images_are_listed_and_can_be_cleared(page: Page) -> None:
    page.goto("/")
    page.set_input_files("#images", OLD_TOM)

    expect(page.locator(".file-list li")).to_have_count(1)
    expect(page.locator(".file-list")).to_contain_text("label.png")
    page.click("button.clear-files")
    expect(page.locator(".file-list li")).to_have_count(0)


def test_pasted_application_text_fills_the_fields(page: Page) -> None:
    page.goto("/")
    page.fill(
        "#application_text",
        "Brand Name: OLD TOM DISTILLERY\nImported: yes\nCountry of Origin: Mexico",
    )

    page.click("button.fill-fields")

    expect(page.locator("#brand_name")).to_have_value("OLD TOM DISTILLERY")
    expect(page.locator("#imported")).to_be_checked()
    expect(page.locator("#country_of_origin")).to_have_value("Mexico")
    expect(page.locator(".fill-status")).to_contain_text("Filled")


def test_the_country_appears_only_for_imports(page: Page) -> None:
    page.goto("/")

    expect(page.locator(".country-field")).to_be_hidden()
    page.check("#imported")
    expect(page.locator(".country-field")).to_be_visible()


def test_the_abv_asterisk_shows_only_for_spirits(page: Page) -> None:
    page.goto("/")

    expect(page.locator(".abv-required")).to_be_visible()
    page.select_option("#beverage_type", "wine")
    expect(page.locator(".abv-required")).to_be_hidden()


# ---- batch ----


def test_the_batch_page_has_no_accessibility_violations(page: Page) -> None:
    page.goto("/batch")

    no_violations(page)


def test_the_example_batch_runs_and_lists_failures_first(page: Page) -> None:
    page.goto("/batch")

    page.click("button.run-example")

    expect(page.locator(".batch-summary")).to_contain_text("11 labels", timeout=60_000)
    rows = page.locator(".batch-results tbody tr")
    expect(rows).to_have_count(11)
    ranks = page.evaluate(
        "Array.from(document.querySelectorAll('.batch-results tbody tr')).map(r => r.dataset.rank)"
    )
    assert ranks == sorted(ranks)
    no_violations(page)


def test_a_spreadsheet_and_images_are_checked_and_a_missing_image_is_reported(
    page: Page, tmp_path: object
) -> None:
    from pathlib import Path

    sheet = Path(str(tmp_path)) / "labels.csv"
    sheet.write_text(
        "images,beverage_type,brand_name,class_type,alcohol_content,net_contents,bottler\n"
        "label.png,spirits,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,"
        '45% Alc./Vol. (90 Proof),750 mL,"Old Tom Distillery, Louisville, Kentucky"\n'
        "missing.png,spirits,OLD TOM DISTILLERY,Bourbon,45%,750 mL,Old Tom\n",
        encoding="utf-8",
    )
    page.goto("/batch")
    page.set_input_files("#sheet", sheet)
    expect(page.locator(".sheet-status")).to_contain_text("2 labels")
    page.set_input_files("#images", OLD_TOM)
    expect(page.locator(".image-status")).to_contain_text("missing.png")

    page.click("button.run-batch")

    expect(page.locator(".batch-summary")).to_contain_text("2 labels", timeout=60_000)
    expect(page.locator(".batch-results")).to_contain_text("Couldn't check")
    expect(page.locator(".batch-results")).to_contain_text("Matches")
    with page.expect_download() as download:
        page.click("button.export-results")
    assert download.value.suggested_filename.endswith(".csv")
