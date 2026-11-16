"""PDF page furniture: mastheads, running heads, figure panels, misleading years.

Each case reproduces what a real NEJM upload produced on the first test run:
the title came back as "The new engl and jour nal of medicine", the year as
2019 (from "Coronavirus disease 2019"), and the running footer and a
Kaplan-Meier panel were quoted as evidence.
"""

from __future__ import annotations

import pytest

from app.ingest.pdf import parse_pdf

pymupdf = pytest.importorskip("pymupdf")

MASTHEAD = "The new engl and jour nal of medicine"
TITLE = "Dexamethasone in Hospitalized Patients with Covid-19"
FOOTER = "n engl j med 384;8 nejm.org February 25, 2021"
BODY = (
    "Coronavirus disease 2019 (Covid-19) is associated with diffuse lung damage. "
    "This article was published on July 17, 2020, at NEJM.org. "
    "In this controlled, open-label trial, we randomly assigned patients to receive "
    "oral or intravenous dexamethasone or to receive usual care alone. "
)
FIGURE = (
    "50 40 30 20 10 0 0 7 14 21 28 Rate ratio, 0.83 (95% CI, 0.75-0.93) "
    "4321 2104 3754 1903 3427 1725 3271 1659 3205 1621 3108 1586"
)


def _build(pages: int = 4) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page(width=595, height=842)
        if index == 0:
            page.insert_text((50, 60), MASTHEAD, fontsize=26, fontname="helv")
            page.insert_text((50, 110), TITLE, fontsize=18, fontname="helv")
        page.insert_textbox(
            pymupdf.Rect(50, 150, 545, 500),
            f"Page {index + 1} section. " + BODY * 3,
            fontsize=9,
            fontname="helv",
        )
        page.insert_textbox(
            pymupdf.Rect(50, 520, 545, 600), FIGURE, fontsize=7, fontname="helv"
        )
        page.insert_text((50, 820), f"{FOOTER} {index + 1}", fontsize=7, fontname="helv")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture(scope="module")
def parsed():
    return parse_pdf(_build())


def test_title_skips_the_journal_masthead(parsed):
    assert parsed.title == TITLE


def test_year_comes_from_a_date_not_from_a_disease_name(parsed):
    assert parsed.year == 2020


def test_running_footer_is_removed(parsed):
    assert "nejm.org February" not in parsed.text
    assert "n engl j med" not in parsed.text


def test_figure_panel_numbers_are_removed(parsed):
    assert "4321 2104 3754" not in parsed.text


def test_body_text_survives(parsed):
    assert "we randomly assigned patients to receive" in parsed.text
    assert parsed.text.count("diffuse lung damage") == 12
