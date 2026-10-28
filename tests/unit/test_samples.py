"""The sample labels offered on the page: a curated set copied from the test fixtures."""

import pytest

from app.web.samples import SAMPLES_ROOT, Sample, load_samples
from scripts.fixtures import FIXTURES_ROOT, load_fixtures

FIXTURES = {
    truth.id: (folder, truth)
    for source in ("synthetic", "cola")
    for folder, truth in load_fixtures(FIXTURES_ROOT / source)
}
SAMPLES = load_samples()


def test_about_ten_samples_cover_drawn_and_real_labels() -> None:
    assert 8 <= len(SAMPLES) <= 12
    assert any(sample.id.startswith("cola-") for sample in SAMPLES)
    assert any(not sample.id.startswith("cola-") for sample in SAMPLES)


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample.id)
def test_each_sample_is_a_faithful_copy_of_its_fixture(sample: Sample) -> None:
    folder, truth = FIXTURES[sample.id]

    assert sample.application == truth.application
    assert sample.description == truth.description
    assert [path.name for path in sample.images] == list(truth.images)
    for path in sample.images:
        assert path.read_bytes() == (folder / path.name).read_bytes()
        assert path.is_relative_to(SAMPLES_ROOT)


def test_a_sample_is_found_only_by_its_exact_id() -> None:
    from app.web.samples import find_sample

    assert find_sample("old-tom") is not None
    assert find_sample("../old-tom") is None
    assert find_sample("OLD-TOM") is None
