"""Text handling: sentence splitting, sectioning, chunking.

The property these tests really defend is *offset integrity*.  Every citation
the platform shows a user is a pair of character offsets into ``raw_text``; if
chunking drifts by even one character, every quote in the UI points at the wrong
place while still looking plausible.  So several tests assert byte-identity
between a chunk's stored text and the slice of the source it claims to be.
"""

from __future__ import annotations

from app.ingest.chunker import chunk_sections
from app.ingest.sectioniser import detect_sections, section_priority
from app.text_utils import clean_pdf_text, count_tokens, split_sentences


class TestSentenceSplitting:
    def test_offsets_index_the_original_string(self):
        text = "First sentence here. Second one follows. Third ends it."
        spans = split_sentences(text)
        assert len(spans) == 3
        for start, end, sentence in spans:
            assert text[start:end] == sentence

    def test_base_offset_is_added(self):
        text = "Alpha runs first. Beta runs second."
        spans = split_sentences(text, base_offset=1000)
        assert spans[0][0] == 1000
        assert all(start >= 1000 for start, _end, _s in spans)

    def test_does_not_split_on_abbreviations(self):
        text = "We compared drug A vs. placebo in adults. Results were clear."
        assert len(split_sentences(text)) == 2

    def test_does_not_split_on_initials(self):
        text = "Analysis followed the method of J. Smith and colleagues. It worked."
        assert len(split_sentences(text)) == 2

    def test_does_not_split_inside_decimals(self):
        text = "The effect was significant (p = 0.001). No harm was seen."
        spans = split_sentences(text)
        assert len(spans) == 2
        assert "0.001" in spans[0][2]

    def test_keeps_terminator_with_its_sentence(self):
        spans = split_sentences("One thing happened. Another followed.")
        assert spans[0][2].endswith(".")

    def test_empty_input(self):
        assert split_sentences("   ") == []


class TestCleanPdfText:
    def test_rejoins_hyphenated_line_breaks(self):
        assert "randomised" in clean_pdf_text("patients were random-\nised to receive")

    def test_unwraps_hard_wrapped_lines(self):
        cleaned = clean_pdf_text("The primary outcome was\nchange in blood pressure.")
        assert "was change" in cleaned

    def test_keeps_paragraph_breaks(self):
        assert "\n\n" in clean_pdf_text("First para.\n\nSecond para.")


class TestSectioniser:
    def test_detects_imrad_headings(self, sample_text):
        names = {section.name for section in detect_sections(clean_pdf_text(sample_text))}
        assert {"methods", "results", "discussion", "conclusion"} <= names

    def test_sections_slice_the_source_exactly(self, sample_text):
        text = clean_pdf_text(sample_text)
        for section in detect_sections(text):
            assert text[section.char_start : section.char_end] == section.text

    def test_sections_do_not_overlap(self, sample_text):
        sections = detect_sections(clean_pdf_text(sample_text))
        ordered = sorted(sections, key=lambda s: s.char_start)
        for previous, following in zip(ordered, ordered[1:], strict=False):
            assert previous.char_end <= following.char_start

    def test_falls_back_to_one_body_section(self):
        sections = detect_sections("Just a paragraph of prose with no headings at all.")
        assert len(sections) == 1
        assert sections[0].name in ("body", "title")

    def test_prose_sentence_is_not_a_heading(self):
        text = "Methods used in this study were adapted from earlier work.\nMore text."
        assert all(s.name != "methods" for s in detect_sections(text))

    def test_section_priority_is_a_multiplier_around_one(self):
        assert section_priority("results", "effect") > 1.0
        assert section_priority("references", "effect") == 1.0


class TestChunker:
    def test_chunk_text_matches_the_source_slice(self, sample_text):
        text = clean_pdf_text(sample_text)
        sections = detect_sections(text)
        for chunk in chunk_sections(sections):
            assert text[chunk.char_start : chunk.char_end] == chunk.text

    def test_chunks_never_cross_a_section(self, sample_text):
        sections = detect_sections(clean_pdf_text(sample_text))
        bounds = {(s.char_start, s.char_end) for s in sections}
        for chunk in chunk_sections(sections):
            assert any(
                start <= chunk.char_start and chunk.char_end <= end
                for start, end in bounds
            )

    def test_references_are_excluded(self):
        text = "Methods\nWe did the study properly.\n\nReferences\n1. Someone et al. 2019."
        sections = detect_sections(text)
        assert any(s.name == "references" for s in sections)
        assert all(c.section_name != "references" for c in chunk_sections(sections))

    def test_order_indices_are_contiguous(self, sample_text):
        chunks = chunk_sections(detect_sections(clean_pdf_text(sample_text)))
        assert [c.order_index for c in chunks] == list(range(len(chunks)))

    def test_overlap_must_be_smaller_than_target(self, sample_text):
        sections = detect_sections(clean_pdf_text(sample_text))
        try:
            chunk_sections(sections, target_tokens=50, overlap_tokens=50)
        except ValueError as exc:
            assert "overlap" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")

    def test_token_count_is_positive(self):
        assert count_tokens("a short clinical sentence") > 0
