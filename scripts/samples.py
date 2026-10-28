"""Copies a curated set of test fixtures into app/samples, for the page's "Sample labels" picker.

    python -m scripts.samples

The fixtures live under tests/, which the container image doesn't include, so the samples are
copied into the app. Each keeps its fixture's id, description, application and images.
"""

import json
import shutil
from pathlib import Path

from scripts.fixtures import FIXTURES_ROOT, load_fixtures

OUTPUT = Path(__file__).resolve().parent.parent / "app" / "samples"
SAMPLE_FILE = "sample.json"

# id -> the title shown in the picker. Each one shows something different.
SAMPLES = {
    "old-tom": "OLD TOM: the example from the brief",
    "old-tom-front-back": "OLD TOM on a front and a back label",
    "title-case-header": 'Warning header in title case ("Government Warning")',
    "near-miss-brand": "A brand that is almost right",
    "injection-visible": "A label that tries to instruct the AI",
    "photo-tilted": "A tilted photo",
    "warning-rotated": "A warning printed sideways",
    "cola-26257001000366": "Real label: Belle Isle bourbon",
    "cola-26245001000184": "Real label: FLOS wine, with words missing from its warning",
    "cola-26119001000813": "Real label: REA 25 soju, in Korean and English",
    "cola-26246001000514": "Real label: Forever Alone ale, warning printed sideways",
}


def generate(out_dir: Path = OUTPUT) -> None:
    fixtures = {
        truth.id: (folder, truth)
        for source in ("synthetic", "cola")
        for folder, truth in load_fixtures(FIXTURES_ROOT / source)
    }
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for sample_id, title in SAMPLES.items():
        folder, truth = fixtures[sample_id]
        target = out_dir / sample_id
        target.mkdir(parents=True)
        for image in truth.images:
            shutil.copyfile(folder / image, target / image)
        record = {
            "id": truth.id,
            "title": title,
            "description": truth.description,
            "application": json.loads(truth.application.model_dump_json(exclude_none=True)),
            "images": list(truth.images),
        }
        (target / SAMPLE_FILE).write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    generate()
    print(f"Wrote {len(SAMPLES)} samples to {OUTPUT}")
