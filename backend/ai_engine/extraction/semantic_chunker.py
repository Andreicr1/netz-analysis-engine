"""Stage 6 — Semantic Markdown Chunking

Takes Mistral OCR markdown output and produces semantically coherent chunks
aligned to document structure. Preserves tables as atomic units, respects
header hierarchy, and applies adaptive sizing by doc_type.

Each chunk output:
{
    "chunk_index":    int,
    "chunk_id":       str,   # {slugified_doc_id}_{chunk_index:04d}  (Azure-key-safe)
    "content":        str,   # chunk text including section header context
    "breadcrumb":     str,   # e.g. "Fee Structure > Management Fee"
    "has_table":      bool,
    "has_numbers":    bool,  # contains financial figures
    "char_count":     int,
    "token_estimate": int,
    "section_type":   str,   # fees|returns|terms|governance|team|portfolio|risk|strategy|other
    # + all metadata from Stages 1-5
}
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _slugify_key(value: str) -> str:
    """Produce an Azure AI Search-safe document key from an arbitrary string.
    Azure only allows: A-Z a-z 0-9 dash underscore equal-sign.
    Spaces and all other punctuation are collapsed to a single underscore.
    """
    slug = re.sub(r"[^A-Za-z0-9\-=]+", "_", value)
    return slug.strip("_") or "doc"


# ============================================================
# CHUNK SIZE CONFIGURATION BY DOC_TYPE
# ============================================================

# (min_chars, target_chars, max_chars)
_CHUNK_SIZES: dict[str, tuple[int, int, int]] = {
    # Legal — large chunks to preserve contractual context
    "legal_lpa":                 (800,  2000, 4000),
    "legal_side_letter":         (800,  2000, 4000),
    "legal_agreement":           (800,  2000, 4000),
    "legal_credit_agreement":    (800,  2000, 4000),
    "legal_intercreditor":       (800,  2000, 4000),
    "legal_security":            (600,  1500, 3000),
    "legal_subscription":        (600,  1500, 3000),
    "legal_amendment":           (600,  1500, 3000),
    "legal_poa":                 (400,  1000, 2000),
    "legal_term_sheet":          (400,  1000, 2000),

    # Financial — smaller chunks, point-in-time data
    "financial_statements":      (300,   800, 1500),
    "financial_nav":             (200,   600, 1200),
    "financial_projections":     (300,   800, 1500),

    # Fund presentations — section-level chunks
    "fund_presentation":         (400,  1000, 2000),
    "fund_profile":              (300,   800, 1500),
    "fund_structure":            (300,   800, 1500),
    "capital_raising":           (400,  1000, 2000),

    # Operational / monitoring
    "operational_monitoring":    (300,   800, 1500),
    "investment_memo":           (500,  1200, 2500),
    "risk_assessment":           (400,  1000, 2000),

    # Regulatory — medium, preserve form context
    "regulatory_compliance":     (400,  1000, 2000),
    "regulatory_qdd":            (400,  1000, 2000),
    "regulatory_cima":           (400,  1000, 2000),

    # Policies — medium-large
    "fund_policy":               (500,  1200, 2500),
    "credit_policy":             (500,  1200, 2500),
    "operational_service":       (400,  1000, 2000),
    "operational_insurance":     (400,  1000, 2000),
    "strategy_profile":          (400,  1000, 2000),
    "org_chart":                 (300,   800, 1500),
    "attachment":                (400,  1000, 2000),

    # Fallback
    "other":                     (400,  1000, 2000),
    "default":                   (400,  1000, 2000),
}


def _get_chunk_sizes(doc_type: str) -> tuple[int, int, int]:
    return _CHUNK_SIZES.get(doc_type, _CHUNK_SIZES["default"])


# ============================================================
# SECTION TYPE CLASSIFIER
# ============================================================

_SECTION_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"fee|carried interest|management fee|performance fee|hurdle|waterfall|"
        r"expense|cost|incentive fee|base fee|preferred return",
        re.IGNORECASE), "fees"),
    (re.compile(
        r"\breturn\b|performance|irr|moic|multiple|yield|distribution|income|"
        r"net asset value|\bnav\b|track record|tvm|tvpi|dpi|rvpi",
        re.IGNORECASE), "returns"),
    (re.compile(
        r"term|duration|commitment period|investment period|fund life|extension|"
        r"maturity|key term|summary of terms|structure|fund size|target size",
        re.IGNORECASE), "terms"),
    (re.compile(
        r"governance|director|board|committee|voting|consent|amendment|"
        r"removal|key person|clawback|side letter|\bmfn\b",
        re.IGNORECASE), "governance"),
    (re.compile(
        r"team|partner|principal|founder|biography|\bbio\b|experience|"
        r"background|personnel|investment committee|management team|staff",
        re.IGNORECASE), "team"),
    (re.compile(
        r"portfolio|investment|deal|transaction|position|holding|"
        r"borrower|loan|credit|collateral|asset|origination",
        re.IGNORECASE), "portfolio"),
    (re.compile(
        r"risk|covenant|restriction|limit|concentration|default|"
        r"breach|compliance|regulation|watchlist",
        re.IGNORECASE), "risk"),
    (re.compile(
        r"market|macro|outlook|commentary|strategy|thesis|opportunity|"
        r"sector|industry|pipeline|landscape",
        re.IGNORECASE), "strategy"),
]


# doc_types where financial section classification does not apply
_NON_FINANCIAL_DOC_TYPES = frozenset({
    "operational_service", "org_chart", "regulatory_compliance",
    "regulatory_qdd", "risk_assessment", "attachment", "other",
    "credit_policy",  # credit policy uses risk/terms, not fund fees/returns
})

# section_types that only make sense in financial/fund documents
_FINANCIAL_SECTION_TYPES = frozenset({
    "fees", "returns",
})


def _classify_section_type(
    header_text: str,
    content: str = "",
    doc_type: str = "",
) -> str:
    text = f"{header_text} {content[:200]}"
    for pattern, section_type in _SECTION_TYPE_PATTERNS:
        if pattern.search(text):
            # Skip financial section types for non-financial doc_types
            if (
                section_type in _FINANCIAL_SECTION_TYPES
                and doc_type in _NON_FINANCIAL_DOC_TYPES
            ):
                continue
            return section_type
    return "other"


# ============================================================
# FINANCIAL FIGURE DETECTOR
# ============================================================

_HAS_NUMBERS = re.compile(
    r"\d+\.?\d*\s*%"                       # percentages: 18.5%, 8%
    r"|\$[\d,]+\.?\d*"                     # USD: $1,250,000
    r"|R\$[\d,]+\.?\d*"                    # BRL: R$50,000,000
    r"|[\d,]+\.?\d*[xX]\b"                 # multiples: 1.8x
    r"|\b\d+\.?\d*[xX]\s"                  # multiples with space
    r"|(?:USD|EUR|GBP|BRL|CHF)\s*[\d,]+"  # currency amounts
    r"|\b(?:IRR|MOIC|NAV|AUM)\s*:?\s*[\d]",  # labeled metrics
)


def _has_financial_figures(text: str) -> bool:
    return bool(_HAS_NUMBERS.search(text))


# ============================================================
# MARKDOWN PARSER — split into structural blocks
# ============================================================

@dataclass
class Block:
    """A structural unit from the markdown: header, paragraph, table, or list."""
    type:  str   # "header" | "table" | "paragraph" | "list"
    level: int   # header level (1-6), 0 for non-headers
    text:  str
    raw:   str   # original markdown


def _is_pipe_row(line: str) -> bool:
    """Returns True when a line is a Markdown table row or separator.
    A table row starts and ends with | and has ≥ 2 pipe characters.
    Matches both data rows  (| Fund | NAV |)
    and separator rows     (| ---- | --- |)
    without requiring a specific look-ahead.
    """
    s = line.strip()
    return bool(s) and s.startswith("|") and s.endswith("|") and s.count("|") >= 2

# Mistral OCR sometimes exports tables as external HTML files and references
# them as self-referential markdown links instead of emitting inline HTML.
# Pattern: [tbl-12.html](tbl-12.html) or [table_001.html](table_001.html)
# These lines must be treated as table blocks so has_table propagates correctly.
_MISTRAL_TABLE_LINK_RE = re.compile(
    r"\[[^\]]+\.html\]\([^)]+\.html\)",
    re.IGNORECASE,
)


def _split_html_table(table_html: str, max_chars: int) -> list[str]:
    """Split an oversized HTML table into smaller sub-tables of ≤ max_chars.

    Preserves the header row (first <tr> with <th> or the very first <tr>)
    in every sub-table so each chunk is self-contained.
    Returns a list of complete <table>…</table> strings.
    If the table is already ≤ max_chars, returns it as-is in a single-item list.
    """
    if len(table_html) <= max_chars:
        return [table_html]

    # Extract rows
    rows = re.findall(r"<tr[^>]*>.*?</tr>", table_html, re.DOTALL | re.IGNORECASE)
    if not rows:
        return [table_html]

    # Detect header row (contains <th> tags)
    header_row = rows[0] if (re.search(r"<th[\s>]", rows[0], re.IGNORECASE) or len(rows) == 1) else None
    data_rows = rows[1:] if header_row else rows

    # Build sub-tables
    sub_tables: list[str] = []
    current_rows: list[str] = []
    current_size = 0
    wrapper_overhead = len("<table></table>") + (len(header_row) if header_row else 0)

    for row in data_rows:
        row_size = len(row)
        projected = wrapper_overhead + current_size + row_size

        if current_rows and projected > max_chars:
            # Flush current sub-table
            inner = (header_row or "") + "".join(current_rows)
            sub_tables.append(f"<table>{inner}</table>")
            current_rows = []
            current_size = 0

        current_rows.append(row)
        current_size += row_size

    # Flush remaining
    if current_rows:
        inner = (header_row or "") + "".join(current_rows)
        sub_tables.append(f"<table>{inner}</table>")

    return sub_tables if sub_tables else [table_html]


def _parse_markdown_blocks(markdown: str) -> list[Block]:
    """Parse markdown into structural blocks.
    HTML tables (from Mistral OCR table_format=html) are treated as atomic units.
    Markdown pipe-tables are also collected as single blocks.
    """
    blocks: list[Block] = []
    lines = markdown.split("\n")
    i     = 0

    while i < len(lines):
        line = lines[i]

        # HTML table — collect until </table>
        # Handles: <table>, <table border="1">, <table style="...">, indented tables
        # NOTE: Mistral OCR with table_format="html" often emits entire tables on
        # a SINGLE line (e.g. <table>…</table>). We must check the opening line
        # for </table> first; otherwise the loop would skip past it and eat all
        # subsequent lines up to the next </table> (or EOF).
        if re.search(r"<table[\s>/]|<table>$", line, re.IGNORECASE):
            table_lines = [line]
            if re.search(r"</table>", line, re.IGNORECASE):
                # Self-contained single-line table → don't collect further
                i += 1
            else:
                i += 1
                while i < len(lines):
                    table_lines.append(lines[i])
                    if re.search(r"</table>", lines[i], re.IGNORECASE):
                        i += 1
                        break
                    i += 1
            raw = "\n".join(table_lines)
            blocks.append(Block(type="table", level=0, text=raw, raw=raw))
            continue

        # Mistral external-table-file link — [tbl-12.html](tbl-12.html)
        # Mistral exports some tables as separate HTML files and references them
        # as self-referential markdown links. Treat as a table block.
        if _MISTRAL_TABLE_LINK_RE.search(line):
            blocks.append(Block(type="table", level=0, text=line, raw=line))
            i += 1
            continue

        # Markdown header
        header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if header_match:
            level = len(header_match.group(1))
            text  = header_match.group(2).strip()
            blocks.append(Block(type="header", level=level, text=text, raw=line))
            i += 1
            continue

        # Markdown pipe-table — with OR without a separator row.
        # Mistral OCR frequently omits the |---|---| separator line.
        # Detect any run of lines where each looks like a pipe row.
        if _is_pipe_row(line):
            table_lines = [line]
            i += 1
            while i < len(lines) and _is_pipe_row(lines[i]):
                table_lines.append(lines[i])
                i += 1
            raw = "\n".join(table_lines)
            blocks.append(Block(type="table", level=0, text=raw, raw=raw))
            continue

        # Legacy: first line has | anywhere + NEXT line is a pure separator
        # (catches the rare case where the header row doesn't start/end with |)
        if "|" in line and i + 1 < len(lines) and re.match(r"^[\|\s\-:]+$", lines[i + 1].strip()):
            table_lines = [line]
            i += 1
            while i < len(lines) and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1
            raw = "\n".join(table_lines)
            blocks.append(Block(type="table", level=0, text=raw, raw=raw))
            continue

        # Empty line — skip
        if not line.strip():
            i += 1
            continue

        # List item — collect contiguous list lines
        if re.match(r"^\s*[-*•]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            list_lines = [line]
            i += 1
            while i < len(lines) and (
                re.match(r"^\s*[-*•]\s+", lines[i]) or
                re.match(r"^\s*\d+\.\s+", lines[i]) or
                (lines[i].startswith("  ") and list_lines)
            ):
                list_lines.append(lines[i])
                i += 1
            raw = "\n".join(list_lines)
            blocks.append(Block(type="list", level=0, text=raw, raw=raw))
            continue

        # Paragraph — collect until blank line, header, or table
        para_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if not next_line.strip():
                break
            if re.match(r"^#{1,6}\s+", next_line):
                break
            if re.search(r"<table[\s>/]|<table>$", next_line, re.IGNORECASE):
                break
            if _MISTRAL_TABLE_LINK_RE.search(next_line):
                break
            if _is_pipe_row(next_line):
                break
            if "|" in next_line and i + 1 < len(lines) and re.match(r"^[\|\s\-:]+$", lines[i + 1].strip()):
                break
            para_lines.append(next_line)
            i += 1
        raw = "\n".join(para_lines)
        blocks.append(Block(type="paragraph", level=0, text=raw, raw=raw))

    return blocks


# ============================================================
# CHUNK BUILDER
# ============================================================

@dataclass
class Chunk:
    chunk_index:    int
    chunk_id:       str
    content:        str
    breadcrumb:     str
    has_table:      bool
    has_numbers:    bool
    char_count:     int
    token_estimate: int
    section_type:   str
    metadata:       dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_index":    self.chunk_index,
            "chunk_id":       self.chunk_id,
            "content":        self.content,
            "breadcrumb":     self.breadcrumb,
            "has_table":      self.has_table,
            "has_numbers":    self.has_numbers,
            "char_count":     self.char_count,
            "token_estimate": self.token_estimate,
            "section_type":   self.section_type,
            **self.metadata,
        }


def _build_breadcrumb(header_stack: list[tuple[int, str]]) -> str:
    """'Fee Structure > Management Fee' from the current header stack (last 3 levels)."""
    if not header_stack:
        return ""
    return " > ".join(h[1] for h in header_stack[-3:])


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English financial text."""
    return len(text) // 4


def _chunk_markdown(
    markdown: str,
    doc_id:   str,
    doc_type: str,
    metadata: dict,
) -> list[Chunk]:
    """Core chunking logic. Returns list of Chunk objects.

    Rules:
    - Tables are always atomic — never split across chunks.
    - H1/H2 headers trigger a flush when the accumulator is ≥ min_chars.
    - Paragraphs/lists accumulate until target_chars, then flush.
    - Blocks that alone exceed max_chars produce an oversized chunk (never truncated).
    - Every chunk is prefixed with its breadcrumb for LLM context.
    """
    min_chars, target_chars, max_chars = _get_chunk_sizes(doc_type)
    blocks      = _parse_markdown_blocks(markdown)
    chunks:     list[Chunk] = []
    chunk_index = 0

    header_stack:   list[tuple[int, str]] = []
    current_blocks: list[Block] = []
    current_chars:  int = 0

    def flush_chunk() -> None:
        nonlocal current_blocks, current_chars, chunk_index

        if not current_blocks:
            return

        content = "\n\n".join(b.raw for b in current_blocks).strip()
        if not content:
            current_blocks = []
            current_chars  = 0
            return

        breadcrumb   = _build_breadcrumb(header_stack)
        full_content = f"[{breadcrumb}]\n\n{content}" if breadcrumb else content

        has_tbl  = any(b.type == "table" for b in current_blocks)
        has_nums = _has_financial_figures(content)
        sec_type = _classify_section_type(
            breadcrumb,
            next((b.text for b in current_blocks if b.type == "paragraph"), ""),
            doc_type=doc_type,
        )

        chunks.append(Chunk(
            chunk_index    = chunk_index,
            chunk_id       = f"{_slugify_key(doc_id)}_{chunk_index:04d}",
            content        = full_content,
            breadcrumb     = breadcrumb,
            has_table      = has_tbl,
            has_numbers    = has_nums,
            char_count     = len(full_content),
            token_estimate = _estimate_tokens(full_content),
            section_type   = sec_type,
            metadata       = metadata.copy(),
        ))

        chunk_index   += 1
        current_blocks = []
        current_chars  = 0

    for block in blocks:

        # Headers update context but do not produce content blocks
        if block.type == "header":
            # Remove headers at same or deeper level (they're superseded)
            header_stack = [(lvl, txt) for lvl, txt in header_stack if lvl < block.level]
            header_stack.append((block.level, block.text))

            # Major section boundary (H1/H2) — flush if enough content accumulated
            if block.level <= 2 and current_chars >= min_chars:
                flush_chunk()
            continue

        # Tables — always atomic: flush before, add, flush after
        if block.type == "table":
            # Mistral external-table-file reference links (e.g. [tbl-12.html](tbl-12.html))
            # contain no inline content — forcing an atomic flush produces a near-empty
            # chunk (~30 chars). Accumulate them instead so they stay attached to the
            # surrounding context. has_table still propagates because block.type == "table".
            if _MISTRAL_TABLE_LINK_RE.search(block.raw):
                block_chars = len(block.raw)
                if current_chars + block_chars > max_chars and current_chars >= min_chars:
                    flush_chunk()
                current_blocks.append(block)
                current_chars += block_chars
                if current_chars >= target_chars:
                    flush_chunk()
                continue

            # Real table (HTML or pipe rows) — split if oversized
            table_chars = len(block.raw)
            if table_chars > max_chars and re.search(r"<table", block.raw, re.IGNORECASE):
                # Split oversized HTML table into sub-tables
                sub_tables = _split_html_table(block.raw, max_chars)
                for sub_html in sub_tables:
                    if current_chars > 0 and current_chars + len(sub_html) > max_chars:
                        flush_chunk()
                    sub_block = Block(type="table", level=0, text=sub_html, raw=sub_html)
                    current_blocks.append(sub_block)
                    current_chars += len(sub_html)
                    flush_chunk()
                continue

            # Normal-sized table — always atomic
            if current_chars > 0 and current_chars + table_chars > max_chars:
                flush_chunk()
            current_blocks.append(block)
            current_chars += table_chars
            flush_chunk()
            continue

        # Paragraphs / lists — accumulate up to max, flush at target
        block_chars = len(block.raw)

        if current_chars + block_chars > max_chars and current_chars >= min_chars:
            flush_chunk()

        current_blocks.append(block)
        current_chars += block_chars

        if current_chars >= target_chars:
            flush_chunk()

    flush_chunk()  # flush any remaining content

    return chunks


# ============================================================
# PUBLIC API
# ============================================================

def chunk_document(
    ocr_markdown: str,
    doc_id:       str,
    doc_type:     str,
    metadata:     dict,
) -> list[dict]:
    """Entry point for Stage 6.

    Args:
        ocr_markdown: Full markdown string from Mistral OCR (Stage 1).
        doc_id:       Unique document identifier (e.g. filename stem, no extension).
        doc_type:     Classified doc_type from Stage 2.
        metadata:     Full metadata dict from Stages 1-5 — copied into every chunk.

    Returns:
        List of chunk dicts ready for embedding (Stage 7) and indexing (Stage 8).

    """
    if not ocr_markdown.strip():
        return []

    return [
        c.to_dict()
        for c in _chunk_markdown(
            markdown = ocr_markdown,
            doc_id   = doc_id,
            doc_type = doc_type,
            metadata = metadata,
        )
    ]


