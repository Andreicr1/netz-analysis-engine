"""Tests for ai_engine.extraction.semantic_chunker — document chunking."""
from __future__ import annotations

from ai_engine.extraction.semantic_chunker import (
    _build_breadcrumb,
    _classify_section_type,
    _estimate_tokens,
    _get_chunk_sizes,
    _has_financial_figures,
    _is_pipe_row,
    _parse_markdown_blocks,
    _slugify_key,
    _split_html_table,
    chunk_document,
)

# ── _slugify_key ─────────────────────────────────────────────────


class TestSlugifyKey:
    def test_simple_text(self):
        assert _slugify_key("hello-world") == "hello-world"

    def test_spaces_replaced(self):
        assert _slugify_key("hello world") == "hello_world"

    def test_special_chars_replaced(self):
        assert _slugify_key("doc@v2!.pdf") == "doc_v2_pdf"

    def test_empty_returns_doc(self):
        assert _slugify_key("") == "doc"

    def test_all_special_returns_doc(self):
        assert _slugify_key("!!!") == "doc"

    def test_uuid_format(self):
        result = _slugify_key("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert result == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ── _get_chunk_sizes ──────────────────────────────────────────────


class TestGetChunkSizes:
    def test_known_doc_type(self):
        min_c, target, max_c = _get_chunk_sizes("legal_lpa")
        assert min_c == 800
        assert target == 2000
        assert max_c == 4000

    def test_financial_statements(self):
        min_c, target, max_c = _get_chunk_sizes("financial_statements")
        assert min_c == 300
        assert target == 800

    def test_unknown_falls_back_to_default(self):
        min_c, target, max_c = _get_chunk_sizes("nonexistent_type")
        assert (min_c, target, max_c) == (400, 1000, 2000)


# ── _classify_section_type ────────────────────────────────────────


class TestClassifySectionType:
    def test_fees_section(self):
        assert _classify_section_type("Management Fee Structure") == "fees"

    def test_returns_section(self):
        assert _classify_section_type("Net IRR Performance") == "returns"

    def test_terms_section(self):
        assert _classify_section_type("Key Terms and Duration") == "terms"

    def test_governance_section(self):
        assert _classify_section_type("Board and Committee Governance") == "governance"

    def test_team_section(self):
        assert _classify_section_type("Investment Team Biographies") == "team"

    def test_portfolio_section(self):
        assert _classify_section_type("Portfolio Holdings") == "portfolio"

    def test_risk_section(self):
        assert _classify_section_type("Risk Factors and Covenants") == "risk"

    def test_strategy_section(self):
        assert _classify_section_type("Market Outlook") == "strategy"

    def test_unknown_returns_other(self):
        assert _classify_section_type("Random Text Here") == "other"

    def test_fees_skipped_for_non_financial_doc(self):
        # "fees" section type should be skipped for credit_policy
        result = _classify_section_type("Fee Schedule", doc_type="credit_policy")
        assert result != "fees"

    def test_fees_allowed_for_financial_doc(self):
        result = _classify_section_type("Fee Schedule", doc_type="legal_lpa")
        assert result == "fees"


# ── _has_financial_figures ────────────────────────────────────────


class TestHasFinancialFigures:
    def test_percentage(self):
        assert _has_financial_figures("Return of 18.5%")

    def test_usd_amount(self):
        assert _has_financial_figures("Total AUM: $1,250,000")

    def test_brl_amount(self):
        assert _has_financial_figures("Investimento: R$50,000,000")

    def test_multiple(self):
        assert _has_financial_figures("MOIC of 1.8x on invested capital")

    def test_irr_label(self):
        assert _has_financial_figures("IRR: 15")

    def test_no_financial(self):
        assert not _has_financial_figures("This is plain text with no numbers")


# ── _is_pipe_row ──────────────────────────────────────────────────


class TestIsPipeRow:
    def test_data_row(self):
        assert _is_pipe_row("| Fund | NAV | Return |")

    def test_separator_row(self):
        assert _is_pipe_row("| ---- | --- | ------ |")

    def test_not_pipe_row(self):
        assert not _is_pipe_row("This is not a table")

    def test_empty(self):
        assert not _is_pipe_row("")

    def test_single_pipe(self):
        assert not _is_pipe_row("| only one pipe")


# ── _parse_markdown_blocks ────────────────────────────────────────


class TestParseMarkdownBlocks:
    def test_header(self):
        blocks = _parse_markdown_blocks("# Title")
        assert len(blocks) == 1
        assert blocks[0].type == "header"
        assert blocks[0].level == 1
        assert blocks[0].text == "Title"

    def test_h3_header(self):
        blocks = _parse_markdown_blocks("### Sub Section")
        assert blocks[0].level == 3

    def test_paragraph(self):
        blocks = _parse_markdown_blocks("Some paragraph text here.")
        assert len(blocks) == 1
        assert blocks[0].type == "paragraph"

    def test_pipe_table(self):
        md = "| Col A | Col B |\n| --- | --- |\n| val1 | val2 |"
        blocks = _parse_markdown_blocks(md)
        assert any(b.type == "table" for b in blocks)

    def test_html_table_single_line(self):
        md = "<table><tr><td>data</td></tr></table>"
        blocks = _parse_markdown_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].type == "table"

    def test_html_table_multiline(self):
        md = "<table>\n<tr><td>row1</td></tr>\n<tr><td>row2</td></tr>\n</table>"
        blocks = _parse_markdown_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].type == "table"

    def test_list(self):
        md = "- item one\n- item two\n- item three"
        blocks = _parse_markdown_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].type == "list"

    def test_numbered_list(self):
        md = "1. first\n2. second"
        blocks = _parse_markdown_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].type == "list"

    def test_empty_lines_skipped(self):
        md = "\n\n\nSome text\n\n\n"
        blocks = _parse_markdown_blocks(md)
        assert len(blocks) == 1

    def test_mixed_content(self):
        md = "# Title\n\nParagraph text.\n\n| A | B |\n| - | - |\n| 1 | 2 |"
        blocks = _parse_markdown_blocks(md)
        types = [b.type for b in blocks]
        assert "header" in types
        assert "paragraph" in types
        assert "table" in types


# ── _build_breadcrumb ─────────────────────────────────────────────


class TestBuildBreadcrumb:
    def test_empty(self):
        assert _build_breadcrumb([]) == ""

    def test_single_level(self):
        assert _build_breadcrumb([(1, "Title")]) == "Title"

    def test_two_levels(self):
        result = _build_breadcrumb([(1, "Main"), (2, "Sub")])
        assert result == "Main > Sub"

    def test_truncates_to_last_three(self):
        stack = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]
        result = _build_breadcrumb(stack)
        assert result == "B > C > D"


# ── _estimate_tokens ──────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty(self):
        assert _estimate_tokens("") == 0

    def test_short_text(self):
        assert _estimate_tokens("abcd") == 1

    def test_longer_text(self):
        assert _estimate_tokens("A" * 400) == 100


# ── _split_html_table ─────────────────────────────────────────────


class TestSplitHtmlTable:
    def test_small_table_not_split(self):
        table = "<table><tr><td>data</td></tr></table>"
        result = _split_html_table(table, 10000)
        assert len(result) == 1
        assert result[0] == table

    def test_large_table_split(self):
        rows = "".join(f"<tr><td>{'X' * 100}</td></tr>" for _ in range(20))
        table = f"<table><tr><th>Header</th></tr>{rows}</table>"
        result = _split_html_table(table, 500)
        assert len(result) > 1
        for sub in result:
            assert sub.startswith("<table>")
            assert sub.endswith("</table>")

    def test_no_rows_returns_as_is(self):
        table = "<table>no rows here</table>"
        result = _split_html_table(table, 10)
        assert result == [table]


# ── chunk_document (public API) ──────────────────────────────────


class TestChunkDocument:
    def test_empty_text_returns_empty(self):
        assert chunk_document("", "doc1", "legal_lpa", {}) == []

    def test_whitespace_only_returns_empty(self):
        assert chunk_document("   \n  \n  ", "doc1", "other", {}) == []

    def test_basic_chunking(self):
        text = "# Introduction\n\n" + "This is a paragraph. " * 100
        chunks = chunk_document(text, "doc1", "other", {"source": "test"})
        assert len(chunks) > 0
        assert all("content" in c for c in chunks)
        assert all("chunk_index" in c for c in chunks)
        assert all("chunk_id" in c for c in chunks)
        assert all("section_type" in c for c in chunks)

    def test_metadata_propagated(self):
        text = "# Section\n\nSome content here. " * 50
        meta = {"doc_type": "legal_lpa", "fund_name": "Test Fund"}
        chunks = chunk_document(text, "doc1", "legal_lpa", meta)
        assert len(chunks) > 0
        assert chunks[0].get("fund_name") == "Test Fund"

    def test_chunk_ids_are_unique(self):
        text = "# A\n\n" + "Paragraph. " * 200 + "\n\n# B\n\n" + "More text. " * 200
        chunks = chunk_document(text, "doc1", "other", {})
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids))

    def test_table_detection(self):
        text = "| Col A | Col B |\n| --- | --- |\n| 1 | 2 |"
        chunks = chunk_document(text, "doc1", "other", {})
        assert len(chunks) > 0
        assert any(c["has_table"] for c in chunks)

    def test_financial_figures_detection(self):
        text = "The fund returned 18.5% with a MOIC of 1.8x on $1,250,000 invested."
        chunks = chunk_document(text, "doc1", "fund_presentation", {})
        assert len(chunks) > 0
        assert any(c["has_numbers"] for c in chunks)

    def test_breadcrumb_from_headers(self):
        text = "# Main Section\n\n## Subsection\n\nContent here. " * 30
        chunks = chunk_document(text, "doc1", "other", {})
        assert any(c["breadcrumb"] for c in chunks)

    def test_chunk_index_sequential(self):
        text = "# A\n\n" + "Text. " * 300 + "\n\n# B\n\n" + "More. " * 300
        chunks = chunk_document(text, "doc1", "other", {})
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(indices)))

    def test_token_estimate_positive(self):
        text = "Some content for chunking. " * 50
        chunks = chunk_document(text, "doc1", "other", {})
        assert all(c["token_estimate"] > 0 for c in chunks)
