"""The README: the sections the brief asks for, a complete contents list, and no broken links."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
TEXT = re.sub(r"^```.*?^```", "", README, flags=re.M | re.S)  # code blocks hold no headings
HEADINGS = re.findall(r"^#{2,3} (.+)$", TEXT, flags=re.M)
LINKS = re.findall(r"\]\(([^)\s]+)\)", TEXT)


def _anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_the_readme_has_the_sections_the_brief_asks_for() -> None:
    # Setup and run instructions; approach, tools used, assumptions; trade-offs and limitations.
    for section in (
        "Try it",
        "How it works",
        "Tools used",
        "Assumptions",
        "Trade-offs",
        "Limitations",
        "Where the data goes",
        "Run it",
    ):
        assert section in HEADINGS, section


def test_the_contents_list_every_section() -> None:
    contents = TEXT.split("## Contents", 1)[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"\]\(#([^)]+)\)", contents))
    sections = re.findall(r"^## (.+)$", TEXT, flags=re.M)

    assert {_anchor(heading) for heading in sections if heading != "Contents"} <= listed


def test_every_link_within_the_readme_points_to_a_heading() -> None:
    anchors = {_anchor(heading) for heading in HEADINGS}

    assert [link for link in LINKS if link.startswith("#") and link[1:] not in anchors] == []


def test_every_link_to_a_file_points_to_one_in_the_repository() -> None:
    files = [
        link.split("#", 1)[0]
        for link in LINKS
        if not link.startswith(("#", "http://", "https://", "mailto:"))
    ]

    assert files
    assert [path for path in files if not (ROOT / path).exists()] == []
