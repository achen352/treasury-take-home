"""The test-label generator: the approved fixture set, reproducible, with its tricks intact."""

from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageFont, ImageStat

from app.domain.models import Verdict
from scripts import generate_labels
from scripts.fixtures import FIXTURES_ROOT, FixtureTruth, load_fixtures

SYNTHETIC = FIXTURES_ROOT / "synthetic"
BACKGROUNDS = FIXTURES_ROOT / "backgrounds"

M, R, D = Verdict.MATCHES, Verdict.NEEDS_REVIEW, Verdict.DOES_NOT_MATCH
NEVER_MATCHES = {R, D}
HARD_TO_READ = {M, R}

EXPECTED: dict[str, set[Verdict]] = {
    # labels with known answers
    "old-tom": {M},
    "old-tom-front-back": {M},
    "title-case-header": {D},
    "header-not-bold": {D},
    "bold-body": {D},
    "reworded-warning": {D},
    "missing-warning": {D},
    "warning-typo": {D},
    "wrong-abv": {D},
    "proof-mismatch": {D},
    "wrong-net-contents": {D},
    "stones-throw-case": {M},
    "near-miss-brand": {R},
    "wine": {M},
    "beer-no-abv": {M},
    "import-with-country": {M},
    "import-without-country": {D},
    # adversarial: must never come out "Matches"
    "injection-visible": NEVER_MATCHES,
    "injection-low-contrast": NEVER_MATCHES,
    "injection-fix-typos": NEVER_MATCHES,
    "injection-header-bold-claim": NEVER_MATCHES,
    "hidden-transparent-text": NEVER_MATCHES,
    "script-brand": NEVER_MATCHES,
    "template-brand": NEVER_MATCHES,
    "sticker-over-brand": NEVER_MATCHES,
    # hard to read: a compliant label, photographed badly
    "photo-tilted": HARD_TO_READ,
    "photo-curved": HARD_TO_READ,
    "photo-dim": HARD_TO_READ,
    "photo-blurred": HARD_TO_READ,
    "photo-heavy-jpeg": HARD_TO_READ,
    "photo-glare-spot": HARD_TO_READ,
    "warning-rotated": HARD_TO_READ,
    "warning-tiny": HARD_TO_READ,
    "photo-bar-counter": HARD_TO_READ,
    "photo-bottle": HARD_TO_READ,
    "photo-kitchen-counter": HARD_TO_READ,
    "glare-wipes-warning": NEVER_MATCHES,
}


def committed() -> dict[str, tuple[Path, FixtureTruth]]:
    return {truth.id: (folder, truth) for folder, truth in load_fixtures(SYNTHETIC)}


def image(fixture: str, index: int = 0) -> Image.Image:
    folder, truth = committed()[fixture]
    return Image.open(folder / truth.images[index])


def test_generator_produces_exactly_the_approved_fixtures() -> None:
    fixtures = committed()

    assert set(fixtures) == set(EXPECTED)
    for fixture, acceptable in EXPECTED.items():
        assert set(fixtures[fixture][1].acceptable) == acceptable, fixture


def test_committed_fixtures_are_exactly_what_the_generator_makes(tmp_path: Path) -> None:
    generate_labels.generate(tmp_path)

    for fixture, (folder, truth) in committed().items():
        fresh = tmp_path / folder.name
        assert sorted(p.name for p in fresh.iterdir()) == sorted(p.name for p in folder.iterdir())
        assert (fresh / "truth.json").read_text() == (folder / "truth.json").read_text(), fixture
        for name in truth.images:
            with Image.open(folder / name) as old, Image.open(fresh / name) as new:
                assert (old.mode, old.size) == (new.mode, new.size), name
                difference = ImageChops.difference(old.convert("RGBA"), new.convert("RGBA"))
                assert max(ImageStat.Stat(difference).mean) <= 1.0, f"{fixture}/{name}"


def test_only_bundled_open_licensed_fonts_are_used() -> None:
    font_dir = generate_labels.FONT_DIR

    assert (font_dir / "LICENSE").is_file()
    for path in generate_labels.FONTS.values():
        assert path.parent == font_dir
        assert path.is_file()


def test_front_and_back_fixture_has_two_images() -> None:
    _, truth = committed()["old-tom-front-back"]

    assert len(truth.images) == 2
    assert truth.printed.brand_name
    assert truth.printed.health_warning


def test_hidden_text_is_in_fully_transparent_pixels_and_invisible_once_flattened() -> None:
    with image("hidden-transparent-text") as label:
        rgba = label.convert("RGBA")
        transparent = rgba.getchannel("A").point(lambda a: 255 if a == 0 else 0)
        dark = rgba.convert("RGB").convert("L").point(lambda v: 255 if v < 70 else 0)
        hidden_ink = ImageChops.multiply(transparent, dark)
        assert hidden_ink.histogram()[255] > 500  # dark "ink" that has zero opacity
        box = hidden_ink.getbbox()
        assert box is not None
        flattened = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
        assert flattened.crop(box).convert("L").getextrema()[0] > 200  # none of it shows


def test_low_contrast_injection_is_nearly_the_background_colour() -> None:
    ink, paper = generate_labels.LOW_CONTRAST_INK, generate_labels.LABEL_BACKGROUND

    assert _contrast_ratio(ink, paper) < 1.1
    with image("injection-low-contrast") as label:
        assert label.convert("RGB").getcolors(2**24) is not None
        colours = dict((colour, count) for count, colour in label.convert("RGB").getcolors(2**24))
        assert colours.get(ink, 0) > 500


def test_tiny_warning_is_about_four_pixels_tall() -> None:
    font = ImageFont.truetype(generate_labels.FONTS["sans"], generate_labels.TINY_WARNING_SIZE)
    _, top, _, bottom = font.getbbox("H")

    assert bottom - top <= 5


def test_glare_that_wipes_out_the_warning_leaves_no_legible_warning() -> None:
    _, truth = committed()["glare-wipes-warning"]

    assert truth.printed.health_warning is None


@pytest.mark.parametrize("fixture", sorted(f for f, a in EXPECTED.items() if a == NEVER_MATCHES))
def test_adversarial_fixtures_never_match(fixture: str) -> None:
    assert committed()[fixture][1].never_matches


def test_ai_backgrounds_are_committed_with_their_provenance() -> None:
    images = sorted(BACKGROUNDS.glob("*.jpg"))
    provenance = (BACKGROUNDS / "PROVENANCE.md").read_text(encoding="utf-8")

    assert len(images) >= 2
    assert "AI-generated" in provenance
    for path in images:
        assert path.name in provenance


def _contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    def luminance(rgb: tuple[int, int, int]) -> float:
        channels = [c / 255 for c in rgb]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_text_layout_is_the_same_on_every_platform() -> None:
    # Linux builds of Pillow ship the Raqm layout engine and Windows builds don't; pinning the
    # basic engine keeps a fresh generation pixel-identical to the committed fixtures anywhere.
    assert generate_labels.font("sans", 30).layout_engine == ImageFont.Layout.BASIC
