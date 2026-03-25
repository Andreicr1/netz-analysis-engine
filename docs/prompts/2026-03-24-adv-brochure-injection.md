---
date: 2026-03-24
task: adv-brochure-injection-manager-assessment
priority: P0 — required before demo DD report generation
---

# ADV Brochure Text Injection — manager_assessment Chapter

## Context

`sec_manager_brochure_text` is populated with 17,837 sections across 2,157
managers (extracted from ADV Part 2A PDFs today). The table schema is:

- `crd_number` (text)
- `section` (text) — Item label e.g. "item_8", "item_5", "item_9", "item_10"
- `filing_date` (date)
- `content` (text) — full narrative text of the section
- `created_at` (timestamp with time zone)

`AdvService.search_brochure_text()` already exists and has a GIN index on
`content`. However, `sec_injection.py` never calls it — the evidence pack
receives only structured ADV metadata (AUM, fee checkboxes, team bios).

The `manager_assessment.j2` template today infers investment philosophy from
checkboxes. With brochure content available, it should receive the actual
narrative text from ADV Part 2A.

## What to implement

### Step 1 — Read current files before touching anything

```bash
cat backend/vertical_engines/wealth/dd_report/sec_injection.py
cat backend/vertical_engines/wealth/dd_report/evidence_pack.py | head -120
grep -n "adv_" backend/vertical_engines/wealth/prompts/dd_chapters/manager_assessment.j2
grep -n "adv_brochure\|brochure" backend/vertical_engines/wealth/dd_report/evidence_pack.py
```

### Step 2 — Add `gather_sec_adv_brochure()` to `sec_injection.py`

Add a new function after `gather_sec_adv_data()`:

```python
def gather_sec_adv_brochure(
    db: Session,
    crd_number: str | None,
    sections: list[str] | None = None,
) -> dict[str, str]:
    """
    Fetch ADV Part 2A brochure narrative sections for a manager.

    Returns dict keyed by section name with content text.
    Never raises — returns empty dict on any failure.

    sections: list of section names to fetch. Defaults to the 4 most
    relevant for manager_assessment:
        ["item_5", "item_8", "item_9", "item_10"]

    item_5  = Fees and Compensation
    item_8  = Methods of Analysis, Investment Strategies, Risk of Loss
    item_9  = Disciplinary Information
    item_10 = Other Financial Industry Activities and Affiliations
    """
    if not crd_number:
        return {}

    if sections is None:
        sections = ["item_5", "item_8", "item_9", "item_10"]

    try:
        rows = (
            db.execute(
                text("""
                    SELECT section, content
                    FROM sec_manager_brochure_text
                    WHERE crd_number = :crd
                      AND section = ANY(:sections)
                    ORDER BY filing_date DESC, section
                """),
                {"crd": crd_number, "sections": sections},
            )
            .mappings()
            .all()
        )
        # Latest filing wins — first occurrence per section (already sorted by
        # filing_date DESC)
        result: dict[str, str] = {}
        for row in rows:
            if row["section"] not in result:
                result[row["section"]] = row["content"]
        return result
    except Exception:
        return {}
```

### Step 3 — Add `adv_brochure_sections` to `EvidencePack`

In `evidence_pack.py`, add the field to the frozen dataclass:

```python
adv_brochure_sections: dict[str, str] = field(default_factory=dict)
```

Place it after the existing `adv_team` field so the ordering is:
`adv_aum_history` → `adv_fee_structure` → `adv_funds` → `adv_team` →
`adv_brochure_sections`

### Step 4 — Wire into `dd_report_engine.py`

Find where `gather_sec_adv_data()` is called to build the evidence pack.
After that call, add:

```python
adv_brochure = gather_sec_adv_brochure(db, adv_data.get("crd_number"))
```

Then pass `adv_brochure_sections=adv_brochure` when constructing
`EvidencePack`.

Read the engine source to find the exact construction site before editing.

### Step 5 — Update `_CHAPTER_FIELD_EXPECTATIONS` in `evidence_pack.py`

Find `_CHAPTER_FIELD_EXPECTATIONS["manager_assessment"]` and add
`adv_brochure_sections` to the expected fields list. When brochure sections
are present, `structured_data_complete` should be True for manager_assessment
(previously it required ADV metadata — now it requires both metadata AND
at least one brochure section).

Update the completeness check:

```python
"manager_assessment": {
    "expected": [
        "adv_aum_history",
        "adv_fee_structure",
        "adv_team",
        "adv_brochure_sections",  # ADD THIS
    ],
    ...
}
```

`structured_data_complete` for manager_assessment =
`adv_aum_history is not None AND bool(adv_brochure_sections)`

### Step 6 — Update `manager_assessment.j2`

Read the current template first. Then add a brochure content block after the
existing ADV structured data block:

```jinja2
{% if evidence.adv_brochure_sections %}

## ADV Part 2A — Regulatory Disclosures

{% if evidence.adv_brochure_sections.item_8 %}
### Investment Strategy & Methods of Analysis (Item 8)
{{ evidence.adv_brochure_sections.item_8 | truncate(2000) }}
{% endif %}

{% if evidence.adv_brochure_sections.item_5 %}
### Fee Schedule (Item 5)
{{ evidence.adv_brochure_sections.item_5 | truncate(1000) }}
{% endif %}

{% if evidence.adv_brochure_sections.item_9 %}
### Disciplinary Information (Item 9)
{{ evidence.adv_brochure_sections.item_9 | truncate(500) }}
{% endif %}

{% if evidence.adv_brochure_sections.item_10 %}
### Other Financial Activities (Item 10)
{{ evidence.adv_brochure_sections.item_10 | truncate(500) }}
{% endif %}

{% endif %}
```

**Content truncation rationale:**
- item_8 (investment philosophy): 2,000 chars — most important, deserves space
- item_5 (fees): 1,000 chars — supplements structured fee checkboxes
- item_9 (disciplinary): 500 chars — flag presence only
- item_10 (conflicts): 500 chars — flag presence only

Total brochure addition: ~4,000 chars max, well within chapter token budget
of 4,000 tokens (manager_assessment is the largest chapter).

**Also update the LLM instruction block** in the template:

Replace any remaining "where ADV data is available" hedging with:
"ADV Part 2A narrative content is provided above where available. Cite
specific sections by item number (e.g., 'Per Item 8 of the ADV Part 2A...')
when referencing regulatory disclosures."

### Step 7 — Verify never-raises contract

Confirm that if `sec_manager_brochure_text` returns 0 rows for a given CRD
(manager not in our 2,157), the evidence pack still constructs correctly with
`adv_brochure_sections={}` and the template renders without errors
(the `{% if evidence.adv_brochure_sections %}` guard handles this).

---

## Verification

```bash
# Confirm new field in evidence pack
grep -n "adv_brochure_sections" \
  backend/vertical_engines/wealth/dd_report/evidence_pack.py

# Confirm new function in sec_injection
grep -n "gather_sec_adv_brochure" \
  backend/vertical_engines/wealth/dd_report/sec_injection.py

# Confirm template uses it
grep -n "adv_brochure_sections\|item_8\|item_9" \
  backend/vertical_engines/wealth/prompts/dd_chapters/manager_assessment.j2

# Run tests
make check
```

---

## Rules

- Never raises — all DB calls in `gather_sec_adv_brochure` must be wrapped
  in try/except returning `{}`
- Read every file before editing — do not guess field names or class structure
- `content` is the column name (not `brochure_text`)
- `section` values are lowercase with underscore: `item_8`, not `Item 8`
- Do NOT change any other chapter templates — scope is manager_assessment only
- Do NOT change `UpsertResult`, `DDReportResult`, or any API schema
- `make check` must pass before reporting complete

## Success Criteria

- `gather_sec_adv_brochure()` exists in `sec_injection.py`
- `adv_brochure_sections: dict[str, str]` field in `EvidencePack`
- `manager_assessment.j2` renders brochure sections when present, silent
  when absent
- `_CHAPTER_FIELD_EXPECTATIONS["manager_assessment"]` includes
  `adv_brochure_sections`
- `make check` passes
- No API schema changes
