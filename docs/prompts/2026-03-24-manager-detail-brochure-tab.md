---
date: 2026-03-24
task: manager-detail-panel-brochure-tab
priority: P0 — required before demo DD report generation
depends-on: 2026-03-24-adv-brochure-injection.md (backend evidence pack)
---

# ManagerDetailPanel — ADV Part 2A Brochure Tab

## Context

`sec_manager_brochure_text` is populated with 17,837 sections across 2,157
managers. Schema: `crd_number`, `section`, `filing_date`, `content`, `created_at`.

The `ManagerDetailPanel.svelte` (shared between manager-screener and
us-fund-analysis) currently shows 7 tabs: profile, holdings, institutional,
universe, drift, nport, docs.

The Profile tab shows only structured ADV metadata (AUM, CRD, team, funds).
Analysts need to read the actual ADV Part 2A narrative BEFORE deciding to
send a manager to DD Review. This prompt adds an 8th tab: **Brochure**.

## Files to read before touching anything

```
backend/vertical_engines/wealth/screener/routes/manager_screener.py
  — find GET /managers/{crd}/profile endpoint

backend/vertical_engines/wealth/screener/service.py (or schemas.py)
  — find ManagerProfile schema/response model

frontends/wealth/src/lib/components/screener/ManagerDetailPanel.svelte
  — already read: 321 lines, 7 tabs, fetchTab() pattern

frontends/wealth/src/lib/types/manager-screener.ts
  — find ManagerProfile type, DetailTab union
```

---

## Backend changes

### 1. Add brochure endpoint

In `manager_screener.py`, add a new endpoint:

```python
@router.get("/managers/{crd}/brochure")
@route_cache(ttl=3600, key_prefix="mgr:brochure", global_key=True)
async def get_manager_brochure(
    crd: str,
    db: AsyncSession = Depends(get_db),
) -> ManagerBrochureRead:
    """
    Returns ADV Part 2A brochure sections for a manager.
    Sections: item_5 (fees), item_8 (investment strategy),
              item_9 (disciplinary), item_10 (conflicts).
    Returns empty sections dict if manager has no brochure data.
    Never raises — returns gracefully.
    """
```

Query:
```sql
SELECT section, content, filing_date
FROM sec_manager_brochure_text
WHERE crd_number = :crd
  AND section = ANY(ARRAY['item_5','item_8','item_9','item_10'])
ORDER BY filing_date DESC, section
```

Deduplicate: latest filing_date wins per section.

### 2. Add ManagerBrochureRead schema

```python
class BrochureSection(BaseModel):
    section: str
    content: str
    filing_date: date | None = None

class ManagerBrochureRead(BaseModel):
    crd_number: str
    sections: dict[str, BrochureSection]
    # keys: "item_5", "item_8", "item_9", "item_10"
    # empty dict if no brochure data available
```

### 3. TTL rationale

3600s (1 hour) — brochure content is static (monthly ingestion).
`global_key=True` — brochure data is global (no org_id).

---

## Frontend changes

### 1. Update DetailTab type in `manager-screener.ts`

```typescript
export type DetailTab =
  | "profile"
  | "holdings"
  | "institutional"
  | "universe"
  | "drift"
  | "nport"
  | "docs"
  | "brochure";  // ADD THIS

export interface BrochureSection {
  section: string;
  content: string;
  filing_date: string | null;
}

export interface ManagerBrochure {
  crd_number: string;
  sections: Record<string, BrochureSection>;
}
```

### 2. Update ManagerDetailPanel.svelte

**Add state variable:**
```typescript
let brochureData = $state<ManagerBrochure | null>(null);
```

**Reset on panelCrd change** (inside the existing $effect):
```typescript
brochureData = null;
```

**Add case to fetchTab():**
```typescript
case "brochure":
  if (!brochureData) {
    brochureData = await api.get<ManagerBrochure>(
      `/manager-screener/managers/${panelCrd}/brochure`
    );
  }
  break;
```

**Add tab button** — insert after "docs" in the tab list:
```svelte
{#each (["profile","holdings","institutional","universe","drift","nport","docs","brochure"] as DetailTab[]) as tab (tab)}
```

**Tab label mapping** — add to the label expression:
```svelte
tab === "nport" ? "N-PORT"
: tab === "docs" ? "Docs"
: tab === "brochure" ? "ADV 2A"
: tab.charAt(0).toUpperCase() + tab.slice(1)
```

**Add brochure tab content block** after the docs block:

```svelte
{:else if activeTab === "brochure"}
  {#if brochureData}
    {#if Object.keys(brochureData.sections).length === 0}
      <div class="dt-empty">No ADV Part 2A brochure available for this manager.</div>
    {:else}
      {#if brochureData.sections.item_8}
        <div class="dt-section">
          <h4 class="dt-section-title">
            Item 8 — Investment Strategy & Methods of Analysis
            {#if brochureData.sections.item_8.filing_date}
              <span class="dt-section-date">
                Filed {brochureData.sections.item_8.filing_date}
              </span>
            {/if}
          </h4>
          <p class="dt-brochure-text">{brochureData.sections.item_8.content}</p>
        </div>
      {/if}

      {#if brochureData.sections.item_5}
        <div class="dt-section">
          <h4 class="dt-section-title">Item 5 — Fees and Compensation</h4>
          <p class="dt-brochure-text">{brochureData.sections.item_5.content}</p>
        </div>
      {/if}

      {#if brochureData.sections.item_9}
        <div class="dt-section">
          <h4 class="dt-section-title">Item 9 — Disciplinary Information</h4>
          <p class="dt-brochure-text">{brochureData.sections.item_9.content}</p>
        </div>
      {/if}

      {#if brochureData.sections.item_10}
        <div class="dt-section">
          <h4 class="dt-section-title">
            Item 10 — Other Financial Industry Activities
          </h4>
          <p class="dt-brochure-text">{brochureData.sections.item_10.content}</p>
        </div>
      {/if}
    {/if}
  {:else}
    <div class="dt-loading">Loading ADV Part 2A…</div>
  {/if}
```

**Add CSS** to `screener.css`:

```css
.dt-brochure-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--netz-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  padding: 12px;
  background: var(--netz-surface-alt);
  border-radius: 8px;
  border: 1px solid var(--netz-border-subtle);
}

.dt-section-date {
  font-size: 11px;
  font-weight: 400;
  color: var(--netz-text-muted);
  margin-left: 8px;
  text-transform: none;
  letter-spacing: 0;
}
```

---

## Verification

```
# Backend
# Confirm new endpoint exists
grep -r "brochure" backend/vertical_engines/wealth/screener/routes/

# Confirm schema
grep -r "ManagerBrochureRead\|BrochureSection" \
  backend/vertical_engines/wealth/screener/

# Frontend
# Confirm new tab type
grep "brochure" frontends/wealth/src/lib/types/manager-screener.ts

# Confirm panel has brochure tab
grep "ADV 2A\|brochure" \
  frontends/wealth/src/lib/components/screener/ManagerDetailPanel.svelte

make check
```

---

## Rules

- `global_key=True` on the cache decorator — brochure is not org-scoped
- Never raises — empty `sections: {}` is a valid response
- Do NOT modify ProfileData or the profile endpoint — separate concern
- Do NOT modify other tabs — scope is brochure tab only
- `content` is the column name (not `brochure_text`, not `text`)
- `section` values are lowercase underscore: `item_8` not `Item 8`
- Lazy loading — fetch only when tab is clicked (existing fetchTab pattern)
- `make check` must pass

## Success Criteria

- `GET /manager-screener/managers/{crd}/brochure` returns sections dict
- `ManagerDetailPanel` has "ADV 2A" tab (8th tab)
- Clicking tab fetches and renders item_8, item_5, item_9, item_10 sections
- Tab shows "No ADV Part 2A brochure available" when sections is empty
- `make check` passes
- No changes to existing 7 tabs
