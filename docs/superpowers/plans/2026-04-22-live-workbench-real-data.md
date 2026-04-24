# Live Workbench Real Data + Screener Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock `make check-all`, add peer metrics and DD chapter list to ScreenerFundFocusModal, and add auto-refresh to MacroRegimePanel.

**Architecture:** Phase 0 fixes the global gate (credit lint + terminal Svelte errors). Phase 1 adds a new backend endpoint `GET /screener/peer-metrics/{fund_id}` that reads from global `fund_risk_metrics` by `strategy_label` peer group. Phase 2 wires the endpoint + DD chapter list into the existing `ScreenerFundFocusModal` right column via a tab toggle. Phase 3 adds a 60-second polling interval to `MacroRegimePanel` so regional regime data stays fresh without a page reload.

**Tech Stack:** Python/FastAPI, Pydantic v2, asyncpg (SQLAlchemy async), SvelteKit + Svelte 5 runes (`$state`, `$derived`, `$effect`), `@investintell/ui` formatters, `packages/ii-terminal-core/` for all shared components.

**Key facts (read before touching files):**
- `live/+page.svelte` is TypeScript-clean; Svelte-check errors come from imported components in `ii-terminal-core`. Run `pnpm --filter @investintell/ii-terminal-core check` first — that is the source of truth.
- `frontends/credit/` lint errors are formatter violations (`toFixed`, inline `Intl`, etc.) detected by `netzFormatterRules` from the parent ESLint config.
- Watchlist and HoldingsTable already consume `MarketDataStore` via WebSocket — live prices are already wired. No work needed there.
- AlertStreamPanel already reads `/alerts/inbox`. No work needed there.
- `GET /dd-reports/funds/{fund_id}` returns `list[DDReportSummary]` — use it as-is.
- All formatters must come from `@investintell/ui`. Never `.toFixed()`, `toLocaleString()`, or `new Intl.*`.

---

## File Map

**Create:**
- `backend/app/domains/wealth/schemas/screener_peer.py` — `PeerMetricsResponse` Pydantic schema
- `backend/tests/domains/wealth/routes/test_screener_peer_metrics.py` — unit tests for schema + helper logic

**Modify:**
- `backend/app/domains/wealth/routes/screener.py` — add `GET /screener/peer-metrics/{fund_id}`
- `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte` — add PROFILE / DD ANALYSIS tab toggle in right column
- `packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte` — add 60s polling interval
- Files in `frontends/credit/src/` — fix formatter violations (identified in Task 0.1)

---

## Phase 0: Unblock `make check-all`

### Task 0.1: Fix `frontends/credit` lint baseline

**Files:**
- Modify: any files in `frontends/credit/src/` flagged by ESLint

- [ ] **Step 1: Run lint and capture errors**

  ```bash
  pnpm --dir frontends/credit lint 2>&1 | head -80
  ```

  Expected output: list of files with `toFixed`, `toLocaleString`, or `new Intl.` violations.

- [ ] **Step 2: Fix each formatter violation**

  For every file reported, replace:
  - `.toFixed(N)` → `formatNumber(value, N)` (import from `@investintell/ui`)
  - `new Intl.NumberFormat(...).format(x)` → `formatNumber(x)` or `formatCurrency(x)`
  - `new Intl.DateTimeFormat(...).format(d)` → `formatDate(d)` or `formatDateTime(d)`
  - `.toLocaleString(...)` → appropriate formatter from `@investintell/ui`

  Add the import at the top of each fixed file if not already present:
  ```typescript
  import { formatNumber, formatCurrency, formatPercent, formatDate } from "@investintell/ui";
  ```

- [ ] **Step 3: Verify lint passes**

  ```bash
  pnpm --dir frontends/credit lint
  ```

  Expected: zero errors.

- [ ] **Step 4: Commit**

  ```bash
  git add frontends/credit/src/
  git commit -m "fix(credit): replace toFixed/Intl violations with @investintell/ui formatters"
  ```

---

### Task 0.2: Fix `ii-terminal-core` Svelte-check errors

**Files:**
- Modify: whichever component files in `packages/ii-terminal-core/src/` are flagged

- [ ] **Step 1: Run check and capture errors**

  ```bash
  pnpm --filter @investintell/ii-terminal-core check 2>&1 | grep "Error\|error" | head -40
  ```

  Expected: list of `.svelte` files with Svelte-check errors (prop type mismatches, missing exports, etc.).

- [ ] **Step 2: Fix each error**

  Common patterns to fix:
  - Missing required prop → add `?` to make optional or provide default in parent
  - Type `X` is not assignable to `Y` → align the type, usually by widening the prop interface
  - `$props()` destructuring missing field → add the field with a default value

  For each file, read the current code, understand the error context, and apply the minimal fix.

- [ ] **Step 3: Verify check passes**

  ```bash
  pnpm --filter @investintell/ii-terminal-core check
  ```

  Expected: 0 errors (warnings are acceptable).

- [ ] **Step 4: Run terminal check**

  ```bash
  pnpm --dir frontends/terminal check 2>&1 | grep "Error\|error" | grep -v "live/+page" | head -20
  ```

  If errors remain outside `live/+page.svelte`, fix them. Errors IN `live/+page.svelte` that existed before this sprint can be left for the next pass if they are pre-existing.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/ii-terminal-core/src/
  git commit -m "fix(ii-terminal-core): resolve Svelte-check errors to unblock make check-all"
  ```

---

## Phase 1: Backend — Peer Metrics Endpoint

### Task 1.1: `PeerMetricsResponse` schema + tests

Peer metrics reads from the global `fund_risk_metrics` hypertable (no RLS — it's shared across tenants). The query finds the subject fund's `strategy_label` in `instruments_universe`, then fetches the latest metrics for all instruments with the same label, and computes min/median/max for Sharpe and max drawdown.

**Files:**
- Create: `backend/app/domains/wealth/schemas/screener_peer.py`
- Create: `backend/tests/domains/wealth/routes/test_screener_peer_metrics.py`

- [ ] **Step 1: Create the schema file**

  Create `backend/app/domains/wealth/schemas/screener_peer.py`:

  ```python
  from __future__ import annotations

  from pydantic import BaseModel


  class PeerMetricRow(BaseModel):
      ticker: str
      name: str
      sharpe_ratio: float | None
      max_drawdown: float | None


  class PeerMetricsResponse(BaseModel):
      fund_id: str
      strategy_label: str | None
      peer_count: int
      # Subject fund values
      subject_sharpe: float | None
      subject_drawdown: float | None
      # Peer distribution (excluding subject)
      peer_sharpe_p25: float | None
      peer_sharpe_p50: float | None
      peer_sharpe_p75: float | None
      peer_drawdown_p25: float | None
      peer_drawdown_p50: float | None
      peer_drawdown_p75: float | None
      # Top 5 peers by manager_score for the comparison list
      top_peers: list[PeerMetricRow] = []
  ```

- [ ] **Step 2: Write failing tests**

  Create `backend/tests/domains/wealth/routes/test_screener_peer_metrics.py`:

  ```python
  from backend.app.domains.wealth.schemas.screener_peer import (
      PeerMetricRow,
      PeerMetricsResponse,
  )
  import statistics


  def test_peer_metrics_response_schema():
      resp = PeerMetricsResponse(
          fund_id="abc",
          strategy_label="Long/Short Equity",
          peer_count=12,
          subject_sharpe=1.2,
          subject_drawdown=-0.15,
          peer_sharpe_p25=0.8,
          peer_sharpe_p50=1.1,
          peer_sharpe_p75=1.4,
          peer_drawdown_p25=-0.22,
          peer_drawdown_p50=-0.14,
          peer_drawdown_p75=-0.08,
          top_peers=[
              PeerMetricRow(ticker="ABCX", name="ABC Fund", sharpe_ratio=1.3, max_drawdown=-0.12),
          ],
      )
      assert resp.peer_count == 12
      assert resp.subject_sharpe == 1.2
      assert len(resp.top_peers) == 1


  def test_peer_metrics_empty_defaults():
      resp = PeerMetricsResponse(
          fund_id="xyz",
          strategy_label=None,
          peer_count=0,
          subject_sharpe=None,
          subject_drawdown=None,
          peer_sharpe_p25=None,
          peer_sharpe_p50=None,
          peer_sharpe_p75=None,
          peer_drawdown_p25=None,
          peer_drawdown_p50=None,
          peer_drawdown_p75=None,
      )
      assert resp.top_peers == []
      assert resp.strategy_label is None


  def _percentile(values: list[float], p: float) -> float:
      """Same logic used inside the route helper."""
      if not values:
          return 0.0
      sorted_vals = sorted(values)
      idx = (p / 100) * (len(sorted_vals) - 1)
      lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
      return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


  def test_percentile_helper():
      vals = [0.5, 1.0, 1.5, 2.0, 2.5]
      assert _percentile(vals, 50) == 1.5
      assert _percentile(vals, 0) == 0.5
      assert _percentile(vals, 100) == 2.5
  ```

- [ ] **Step 3: Run tests (expect PASS — schema only, no DB)**

  ```bash
  cd backend && python -m pytest tests/domains/wealth/routes/test_screener_peer_metrics.py -v
  ```

  Expected: 3 passing.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/domains/wealth/schemas/screener_peer.py \
          backend/tests/domains/wealth/routes/test_screener_peer_metrics.py
  git commit -m "feat(screener): add PeerMetricsResponse schema + tests"
  ```

---

### Task 1.2: `GET /screener/peer-metrics/{fund_id}` route

**Files:**
- Modify: `backend/app/domains/wealth/routes/screener.py`

- [ ] **Step 1: Add import at top of screener.py**

  In `backend/app/domains/wealth/routes/screener.py`, find the existing imports block and add:

  ```python
  from ..schemas.screener_peer import PeerMetricRow, PeerMetricsResponse
  ```

- [ ] **Step 2: Add the helper function + route after the last existing `@router.get` block**

  Find the last `@router.get` in the file and append after it:

  ```python
  # ── Peer metrics ────────────────────────────────────────────────────────────

  def _pct(values: list[float], p: float) -> float | None:
      if not values:
          return None
      sv = sorted(values)
      idx = (p / 100) * (len(sv) - 1)
      lo, hi = int(idx), min(int(idx) + 1, len(sv) - 1)
      return sv[lo] + (sv[hi] - sv[lo]) * (idx - lo)


  @router.get(
      "/peer-metrics/{fund_id}",
      response_model=PeerMetricsResponse,
      summary="Sharpe/drawdown peer distribution for a fund by strategy_label",
      tags=["screener"],
  )
  async def get_peer_metrics(
      fund_id: str,
      db: AsyncSession = Depends(get_db_with_rls),
      user: CurrentUser = Depends(get_current_user),
  ) -> PeerMetricsResponse:
      """
      Returns the subject fund's Sharpe + max drawdown alongside the peer
      distribution (p25/p50/p75) for funds sharing the same strategy_label.
      Reads from global tables (instruments_universe + fund_risk_metrics) —
      no RLS filter needed.
      """
      from sqlalchemy import text as sa_text

      # 1. Resolve external_id → internal ticker + strategy_label
      resolve = await db.execute(
          sa_text(
              """
              SELECT ticker, name, strategy_label
              FROM instruments_universe
              WHERE external_id = :fid OR ticker = :fid
              LIMIT 1
              """
          ),
          {"fid": fund_id},
      )
      subject_row = resolve.fetchone()
      if not subject_row:
          raise HTTPException(status_code=404, detail="Fund not found in universe")

      subject_ticker: str = subject_row.ticker
      subject_name: str = subject_row.name
      strategy_label: str | None = subject_row.strategy_label

      # 2. Fetch subject metrics
      subj_q = await db.execute(
          sa_text(
              """
              SELECT DISTINCT ON (instrument_id)
                  sharpe_ratio, max_drawdown
              FROM fund_risk_metrics
              WHERE instrument_id = (
                  SELECT id FROM instruments_universe
                  WHERE ticker = :ticker LIMIT 1
              )
              ORDER BY instrument_id, as_of_date DESC
              """
          ),
          {"ticker": subject_ticker},
      )
      subj = subj_q.fetchone()
      subject_sharpe = float(subj.sharpe_ratio) if subj and subj.sharpe_ratio is not None else None
      subject_drawdown = float(subj.max_drawdown) if subj and subj.max_drawdown is not None else None

      if not strategy_label:
          return PeerMetricsResponse(
              fund_id=fund_id,
              strategy_label=None,
              peer_count=0,
              subject_sharpe=subject_sharpe,
              subject_drawdown=subject_drawdown,
              peer_sharpe_p25=None,
              peer_sharpe_p50=None,
              peer_sharpe_p75=None,
              peer_drawdown_p25=None,
              peer_drawdown_p50=None,
              peer_drawdown_p75=None,
          )

      # 3. Fetch peer metrics (same strategy_label, exclude subject)
      peers_q = await db.execute(
          sa_text(
              """
              SELECT DISTINCT ON (frm.instrument_id)
                  iu.ticker,
                  iu.name,
                  frm.sharpe_ratio,
                  frm.max_drawdown,
                  frm.manager_score
              FROM fund_risk_metrics frm
              JOIN instruments_universe iu ON iu.id = frm.instrument_id
              WHERE iu.strategy_label = :sl
                AND iu.ticker != :subject_ticker
              ORDER BY frm.instrument_id, frm.as_of_date DESC
              LIMIT 200
              """
          ),
          {"sl": strategy_label, "subject_ticker": subject_ticker},
      )
      peers = peers_q.fetchall()

      sharpes = [float(p.sharpe_ratio) for p in peers if p.sharpe_ratio is not None]
      drawdowns = [float(p.max_drawdown) for p in peers if p.max_drawdown is not None]

      top_peers = sorted(
          [p for p in peers if p.manager_score is not None],
          key=lambda p: float(p.manager_score),
          reverse=True,
      )[:5]

      return PeerMetricsResponse(
          fund_id=fund_id,
          strategy_label=strategy_label,
          peer_count=len(peers),
          subject_sharpe=subject_sharpe,
          subject_drawdown=subject_drawdown,
          peer_sharpe_p25=_pct(sharpes, 25),
          peer_sharpe_p50=_pct(sharpes, 50),
          peer_sharpe_p75=_pct(sharpes, 75),
          peer_drawdown_p25=_pct(drawdowns, 25),
          peer_drawdown_p50=_pct(drawdowns, 50),
          peer_drawdown_p75=_pct(drawdowns, 75),
          top_peers=[
              PeerMetricRow(
                  ticker=p.ticker,
                  name=p.name,
                  sharpe_ratio=float(p.sharpe_ratio) if p.sharpe_ratio is not None else None,
                  max_drawdown=float(p.max_drawdown) if p.max_drawdown is not None else None,
              )
              for p in top_peers
          ],
      )
  ```

- [ ] **Step 3: Lint + typecheck**

  ```bash
  cd backend && ruff check app/domains/wealth/routes/screener.py app/domains/wealth/schemas/screener_peer.py
  python -m py_compile app/domains/wealth/routes/screener.py app/domains/wealth/schemas/screener_peer.py
  ```

  Expected: no errors.

- [ ] **Step 4: Run tests**

  ```bash
  cd backend && python -m pytest tests/domains/wealth/routes/test_screener_peer_metrics.py -v
  ```

  Expected: 3 passing.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/domains/wealth/routes/screener.py \
          backend/app/domains/wealth/schemas/screener_peer.py
  git commit -m "feat(screener): add GET /screener/peer-metrics/{fund_id} endpoint"
  ```

---

## Phase 2: ScreenerFundFocusModal — Peer Bars + DD Chapters

### Task 2.1: Extend ScreenerFundFocusModal right column with tab toggle

The right column currently shows COMPOSITE PROFILE (radar + axis bars). Add a tab toggle so the user can switch between `PROFILE` and `ANALYSIS`. The `ANALYSIS` tab shows:
- Peer comparison bars (Sharpe + drawdown, subject vs peer p25/p50/p75)
- DD chapters list (from `GET /dd-reports/funds/{fund_id}`, uses `instrumentId` prop)

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte`

- [ ] **Step 1: Add peer metrics state + fetch effect**

  In the `<script>` block of `ScreenerFundFocusModal.svelte`, after the existing `w52` derived block (around line 155), add:

  ```typescript
  // ── Peer metrics ───────────────────────────────────────────────
  interface PeerMetricsResponse {
      strategy_label: string | null;
      peer_count: number;
      subject_sharpe: number | null;
      subject_drawdown: number | null;
      peer_sharpe_p25: number | null;
      peer_sharpe_p50: number | null;
      peer_sharpe_p75: number | null;
      peer_drawdown_p25: number | null;
      peer_drawdown_p50: number | null;
      peer_drawdown_p75: number | null;
      top_peers: Array<{ ticker: string; name: string; sharpe_ratio: number | null; max_drawdown: number | null }>;
  }

  let peerMetrics = $state<PeerMetricsResponse | null>(null);
  let loadingPeer = $state(false);

  $effect(() => {
      const id = fundId;
      if (!id) return;
      let cancelled = false;
      loadingPeer = true;
      api
          .get<PeerMetricsResponse>(`/screener/peer-metrics/${encodeURIComponent(id)}`)
          .then((res) => { if (!cancelled) { peerMetrics = res; loadingPeer = false; } })
          .catch(() => { if (!cancelled) { peerMetrics = null; loadingPeer = false; } });
      return () => { cancelled = true; };
  });

  // ── DD chapters ────────────────────────────────────────────────
  interface DDReportSummary {
      id: string;
      version: number;
      status: string;
      confidence_score: number | null;
      decision_anchor: string | null;
      is_current: boolean;
      created_at: string;
  }

  let ddReports = $state<DDReportSummary[]>([]);
  let loadingDD = $state(false);

  $effect(() => {
      const iid = instrumentId;
      if (!iid) { ddReports = []; return; }
      let cancelled = false;
      loadingDD = true;
      api
          .get<DDReportSummary[]>(`/dd-reports/funds/${encodeURIComponent(iid)}`)
          .then((res) => { if (!cancelled) { ddReports = res ?? []; loadingDD = false; } })
          .catch(() => { if (!cancelled) { ddReports = []; loadingDD = false; } });
      return () => { cancelled = true; };
  });

  // ── Right panel tab ────────────────────────────────────────────
  let rightTab = $state<"profile" | "analysis">("profile");
  ```

- [ ] **Step 2: Replace the right column markup**

  In the `<!-- RIGHT: CompositeRadar + axis bars -->` section (the `<div class="sfm-section">` for COMPOSITE PROFILE), replace its entire content with the tab toggle + conditional panels:

  ```svelte
  <!-- RIGHT: PROFILE / ANALYSIS tab toggle -->
  <div class="sfm-section sfm-section--right">
      <div class="sfm-rtabs">
          <button
              type="button"
              class="sfm-rtab"
              class:sfm-rtab--active={rightTab === "profile"}
              onclick={() => (rightTab = "profile")}
          >COMPOSITE PROFILE</button>
          <button
              type="button"
              class="sfm-rtab"
              class:sfm-rtab--active={rightTab === "analysis"}
              onclick={() => (rightTab = "analysis")}
          >DD ANALYSIS</button>
      </div>

      {#if rightTab === "profile"}
          <!-- Original radar + axis bars (keep existing code exactly) -->
          <div class="sfm-radar-wrap">
              <svg viewBox="0 0 {RADAR_W} {RADAR_H}" width={RADAR_W} height={RADAR_H}>
                  {#each [0.25, 0.5, 0.75, 1.0] as pct}
                      {@const pts = Array.from({ length: N }, (_, i) => {
                          const p = radarPt(i, pct * R);
                          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
                      })}
                      <polygon points={pts.join(" ")} fill="none" stroke="var(--ii-border-subtle,#1A2458)" stroke-width="1"/>
                  {/each}
                  {#each Array.from({ length: N }, (_, i) => i) as i (i)}
                      {@const ep = radarPt(i, R)}
                      <line x1={CX} y1={CY} x2={ep.x} y2={ep.y} stroke="var(--ii-border,#1A2458)" stroke-width="1"/>
                  {/each}
                  <path d={radarPath} fill="var(--ii-brand-primary,#FF965A)" fill-opacity="0.18" stroke="var(--ii-brand-primary,#FF965A)" stroke-width="1.5"/>
                  {#each AXES as label, i (label)}
                      {@const lp = radarPt(i, R + 14)}
                      <text x={lp.x} y={lp.y} text-anchor="middle" dominant-baseline="middle"
                          font-family="var(--ii-font-mono)" font-size="7"
                          fill="var(--ii-text-muted,#6D7DA6)" letter-spacing="0.05em">{label}</text>
                  {/each}
              </svg>
          </div>
          <div class="sfm-axis-bars">
              {#each AXES as label, i (label)}
                  {@const score = axisScores[i] ?? 0}
                  <div class="sfm-axis-row">
                      <span class="sfm-axis-lbl">{label}</span>
                      <span class="sfm-axis-bar-wrap">
                          <span class="sfm-axis-bar" style="width:{score}%"></span>
                      </span>
                      <span class="sfm-axis-val">{formatNumber(score, 0)}</span>
                  </div>
              {/each}
          </div>

      {:else}
          <!-- ANALYSIS: peer bars + DD chapters -->
          {#if peerMetrics && peerMetrics.peer_count > 0}
              <div class="sfm-peer-section">
                  <h4 class="sfm-peer-hd">
                      PEER GROUP
                      {#if peerMetrics.strategy_label}
                          <span class="sfm-peer-label">{peerMetrics.strategy_label}</span>
                      {/if}
                      <span class="sfm-peer-count">n={peerMetrics.peer_count}</span>
                  </h4>

                  <!-- Sharpe comparison bar -->
                  <div class="sfm-peer-metric">
                      <span class="sfm-peer-metric-name">SHARPE</span>
                      <div class="sfm-peer-bar-wrap">
                          {@const p25 = peerMetrics.peer_sharpe_p25 ?? 0}
                          {@const p75 = peerMetrics.peer_sharpe_p75 ?? 1}
                          {@const range = (p75 - p25) || 1}
                          {@const subj = peerMetrics.subject_sharpe}
                          <div class="sfm-peer-range" style="left:{Math.max(0, Math.min(100, ((p25 - p25) / range) * 100))}%; width:{Math.max(0, Math.min(100, ((p75 - p25) / range) * 100))}%"></div>
                          {#if subj !== null}
                              {@const subjPct = Math.max(0, Math.min(100, ((subj - p25) / range) * 100))}
                              <div class="sfm-peer-subject" style="left:{subjPct}%"></div>
                          {/if}
                      </div>
                      <div class="sfm-peer-vals">
                          <span>p25: {peerMetrics.peer_sharpe_p25 != null ? formatNumber(peerMetrics.peer_sharpe_p25, 2) : "—"}</span>
                          <span>med: {peerMetrics.peer_sharpe_p50 != null ? formatNumber(peerMetrics.peer_sharpe_p50, 2) : "—"}</span>
                          <span class:sfm-peer-val-up={(peerMetrics.subject_sharpe ?? 0) >= (peerMetrics.peer_sharpe_p50 ?? 0)}>
                              you: {peerMetrics.subject_sharpe != null ? formatNumber(peerMetrics.subject_sharpe, 2) : "—"}
                          </span>
                      </div>
                  </div>

                  <!-- Drawdown comparison bar -->
                  <div class="sfm-peer-metric">
                      <span class="sfm-peer-metric-name">MAX DD</span>
                      <div class="sfm-peer-bar-wrap">
                          {@const p25 = peerMetrics.peer_drawdown_p25 ?? -0.3}
                          {@const p75 = peerMetrics.peer_drawdown_p75 ?? 0}
                          {@const range = (p75 - p25) || 0.01}
                          {@const subj = peerMetrics.subject_drawdown}
                          <div class="sfm-peer-range" style="left:0%; width:100%"></div>
                          {#if subj !== null}
                              {@const subjPct = Math.max(0, Math.min(100, ((subj - p25) / range) * 100))}
                              <div class="sfm-peer-subject sfm-peer-subject--down" style="left:{subjPct}%"></div>
                          {/if}
                      </div>
                      <div class="sfm-peer-vals">
                          <span>p25: {peerMetrics.peer_drawdown_p25 != null ? formatPercent(peerMetrics.peer_drawdown_p25 * 100, 1) : "—"}</span>
                          <span>med: {peerMetrics.peer_drawdown_p50 != null ? formatPercent(peerMetrics.peer_drawdown_p50 * 100, 1) : "—"}</span>
                          <span class:sfm-peer-val-up={(peerMetrics.subject_drawdown ?? -1) >= (peerMetrics.peer_drawdown_p50 ?? -1)}>
                              you: {peerMetrics.subject_drawdown != null ? formatPercent(peerMetrics.subject_drawdown * 100, 1) : "—"}
                          </span>
                      </div>
                  </div>
              </div>
          {:else if loadingPeer}
              <div class="sfm-analysis-empty">Loading peer data…</div>
          {:else}
              <div class="sfm-analysis-empty">No peer group data available.</div>
          {/if}

          <!-- DD chapters -->
          <div class="sfm-dd-section">
              <h4 class="sfm-peer-hd">DD REPORTS</h4>
              {#if loadingDD}
                  <div class="sfm-analysis-empty">Loading…</div>
              {:else if ddReports.length === 0}
                  <div class="sfm-analysis-empty">No DD reports generated yet.</div>
              {:else}
                  {#each ddReports as r (r.id)}
                      <div class="sfm-dd-row">
                          <span class="sfm-dd-status sfm-dd-status--{r.status.toLowerCase()}">{r.status}</span>
                          <span class="sfm-dd-ver">v{r.version}</span>
                          <span class="sfm-dd-score">{r.confidence_score != null ? formatNumber(Number(r.confidence_score), 0) : "—"}</span>
                          <span class="sfm-dd-anchor">{r.decision_anchor ?? ""}</span>
                      </div>
                  {/each}
              {/if}
          </div>
      {/if}
  </div>
  ```

- [ ] **Step 3: Add CSS for new elements**

  In the `<style>` block, append after the last existing rule:

  ```css
  /* Right panel tabs */
  .sfm-section--right { display: flex; flex-direction: column; min-height: 0; }
  .sfm-rtabs { display: flex; gap: 1px; background: var(--ii-border-subtle); flex-shrink: 0; margin-bottom: 12px; }
  .sfm-rtab {
      flex: 1; background: var(--ii-surface-alt); border: none; cursor: pointer;
      font-family: var(--ii-font-mono); font-size: 9px; font-weight: 700;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--ii-text-muted); padding: 6px 0;
  }
  .sfm-rtab--active { background: var(--ii-surface); color: var(--ii-brand-primary); }

  /* Peer metrics */
  .sfm-peer-section { margin-bottom: 14px; }
  .sfm-peer-hd {
      font-size: 9px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--ii-text-muted); margin: 0 0 8px; display: flex; align-items: center; gap: 8px;
  }
  .sfm-peer-label { color: var(--ii-brand-primary); font-weight: 600; }
  .sfm-peer-count { color: var(--ii-text-muted); margin-left: auto; }
  .sfm-peer-metric { margin-bottom: 10px; }
  .sfm-peer-metric-name { font-size: 9px; letter-spacing: 0.06em; color: var(--ii-text-muted); text-transform: uppercase; display: block; margin-bottom: 4px; }
  .sfm-peer-bar-wrap { position: relative; height: 10px; background: var(--ii-surface-alt); border: 1px solid var(--ii-border-subtle); margin-bottom: 4px; overflow: hidden; }
  .sfm-peer-range { position: absolute; top: 0; bottom: 0; background: var(--ii-border-subtle); }
  .sfm-peer-subject { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--ii-brand-primary); }
  .sfm-peer-subject--down { background: var(--ii-danger, #FF5C7A); }
  .sfm-peer-vals { display: flex; gap: 10px; font-size: 9px; color: var(--ii-text-muted); }
  .sfm-peer-val-up { color: var(--ii-success, #3DD39A); font-weight: 700; }

  /* DD section */
  .sfm-dd-section { border-top: 1px solid var(--ii-border-subtle); padding-top: 10px; }
  .sfm-dd-row {
      display: grid; grid-template-columns: 80px 28px 36px 1fr;
      gap: 8px; align-items: center;
      padding: 3px 0; border-bottom: 1px solid var(--ii-terminal-hair, rgba(102,137,188,0.14));
      font-family: var(--ii-font-mono); font-size: 10px;
  }
  .sfm-dd-status { font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
  .sfm-dd-status--approved { color: var(--ii-success); }
  .sfm-dd-status--pending  { color: var(--ii-warning); }
  .sfm-dd-status--rejected { color: var(--ii-danger); }
  .sfm-dd-status--generating { color: var(--ii-text-muted); }
  .sfm-dd-ver { color: var(--ii-text-muted); font-size: 9px; }
  .sfm-dd-score { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ii-text-primary); }
  .sfm-dd-anchor { font-size: 9px; color: var(--ii-text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .sfm-analysis-empty { font-size: 10px; color: var(--ii-text-muted); padding: 12px 0; font-family: var(--ii-font-mono); }
  ```

- [ ] **Step 4: Typecheck**

  ```bash
  pnpm --filter @investintell/ii-terminal-core check
  ```

  Expected: 0 errors.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte
  git commit -m "feat(screener): add peer bars + DD chapters to ScreenerFundFocusModal right panel"
  ```

---

## Phase 3: MacroRegimePanel — 60s Auto-Refresh

### Task 3.1: Add polling interval to MacroRegimePanel

Currently `MacroRegimePanel` fetches `/macro/regional-regime` once on mount and never refreshes. Regional regime data updates daily from the worker, but the SSE connection for the Live Workbench session can stay open for hours. Add a 60-second interval so the panel stays current.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte`

- [ ] **Step 1: Replace the one-shot `$effect` with a polling effect**

  In `MacroRegimePanel.svelte`, find the existing `$effect` that fetches `/macro/regional-regime` (starts around line 27). Replace it with:

  ```typescript
  async function fetchRegimes(cancelled: () => boolean) {
      loading = true;
      try {
          const res = await api.get<{ regions: RegionalRegimeRow[] }>("/macro/regional-regime");
          if (!cancelled()) { regions = res.regions ?? []; }
      } catch {
          if (!cancelled()) { regions = []; }
      } finally {
          if (!cancelled()) { loading = false; }
      }
  }

  $effect(() => {
      let dead = false;
      fetchRegimes(() => dead);
      const id = setInterval(() => fetchRegimes(() => dead), 60_000);
      return () => {
          dead = true;
          clearInterval(id);
      };
  });
  ```

- [ ] **Step 2: Typecheck**

  ```bash
  pnpm --filter @investintell/ii-terminal-core check
  ```

  Expected: 0 errors.

- [ ] **Step 3: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte
  git commit -m "feat(live): MacroRegimePanel auto-refreshes every 60s"
  ```

---

## Phase 4: Build Gate

### Task 4.1: Full gate verification

- [ ] **Step 1: Run backend tests**

  ```bash
  cd backend && python -m pytest tests/domains/wealth/routes/test_screener_peer_metrics.py tests/domains/wealth/services/test_macro_new_endpoints.py -v
  ```

  Expected: all passing.

- [ ] **Step 2: Lint + typecheck backend**

  ```bash
  cd backend && ruff check app/domains/wealth/routes/screener.py app/domains/wealth/schemas/screener_peer.py
  python -m py_compile app/domains/wealth/routes/screener.py app/domains/wealth/schemas/screener_peer.py
  ```

- [ ] **Step 3: Typecheck ii-terminal-core**

  ```bash
  pnpm --filter @investintell/ii-terminal-core check
  ```

  Expected: 0 errors.

- [ ] **Step 4: Build ii-terminal-core**

  ```bash
  pnpm --filter @investintell/ii-terminal-core build
  ```

  Expected: passes.

- [ ] **Step 5: Credit lint**

  ```bash
  pnpm --dir frontends/credit lint
  ```

  Expected: 0 errors.

- [ ] **Step 6: Final commit if any loose fixes**

  ```bash
  git add -p
  git commit -m "fix: gate cleanup for live-workbench-real-data sprint"
  ```

---

## Self-Review Checklist

| Requirement | Task | Status |
|---|---|---|
| `frontends/credit` lint passes | 0.1 | — |
| `ii-terminal-core` Svelte-check 0 errors | 0.2 | — |
| `GET /screener/peer-metrics/{fund_id}` backend endpoint | 1.1–1.2 | — |
| PeerMetricsResponse schema + 3 tests | 1.1 | — |
| Peer Sharpe/drawdown bars in ScreenerFundFocusModal | 2.1 | — |
| DD chapters list in ScreenerFundFocusModal ANALYSIS tab | 2.1 | — |
| Right column tab toggle PROFILE / DD ANALYSIS | 2.1 | — |
| MacroRegimePanel polls every 60s (not one-shot) | 3.1 | — |
| `pnpm --filter @investintell/ii-terminal-core check` 0 errors | 4.1 | — |
| `pnpm --filter @investintell/ii-terminal-core build` passes | 4.1 | — |
| All new backend tests pass | 4.1 | — |

**Deferred (not in this sprint):**
- `live/+page.svelte` pre-existing Svelte-check errors (may require deep ii-terminal-core audit)
- Real MacroNewsFeed data (requires news API provider contract)
- ChartToolbar remove `6M` timeframe
- Builder CalibrationPanel preset buttons
