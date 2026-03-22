# Figma Make Prompt — Netz Wealth OS Redesign

> Copy each section below as a separate Figma Make prompt. Each generates one frame.
> Use together as a multi-frame project to simulate the full redesigned experience.

---

## Prompt 1 — Dashboard (Dark Mode)

```
Design a dark-mode dashboard for "Netz Wealth OS", an institutional investment analysis platform used by portfolio managers, CIOs, and wealth ops teams. Desktop viewport 1440×900.

COLOR SYSTEM (use exactly these hex values):
- Page background: #0c1220 (very dark navy)
- Subtle gradient at top: linear gradient from #0c1220 blended with 20% #84a8d0 at top, fading to pure #0c1220 at 240px — creates a barely-visible navy wash at the page header zone
- Card surfaces: #1a2d44 (clearly distinguishable from page background — this is critical, there must be visible contrast between cards and background)
- Card surface alternate: #152638
- Elevated surfaces (dropdowns, popovers): #243a52
- Inset surfaces (form fields inside cards): #0b121c (darker than card, recessed look)
- Borders: #2a3d55 (subtle but visible on cards), #345270 (stronger, for interactive elements and form fields)
- Text primary: #f4f7fb
- Text secondary: #c0cad7
- Text muted: #8d9caf
- Brand accent (used sparingly for active states, links): #84a8d0 (light blue)
- Brand highlight (used for the Netz logo mark and occasional warm accent): #d49a68 (warm copper-orange)
- Success: #39b38d
- Warning: #d6a24a
- Danger: #e07c89
- Chart palette: #84a8d0, #57c2a0, #d49a68, #a6b7ca, #8da9ff

TYPOGRAPHY:
- Font: Inter (body/UI) + JetBrains Mono (all numbers, financial data, metrics)
- Headings: tracking -0.03em, semibold
- Labels/kickers: 11px uppercase, tracking 0.08em, text muted color, semibold
- Data values: JetBrains Mono, 28px, semibold
- Body: 14px, regular

COMPONENT STYLING:
- Border radius: 14px for cards, 10px for inputs/badges, 18px for larger containers
- Cards have 1px border #2a3d55 plus a subtle combined shadow: "0 1px 3px rgba(0,0,0,0.5), 0 0 0 1px #2a3d55" — both border and shadow-border for elevation in dark mode
- MetricCard signature: 3px solid left border colored by status (green for ok, amber for warning, red for breach). This left accent bar is the strongest visual signature — use it consistently
- Buttons: filled navy with brand-accent text. Hover lifts 1px with deeper shadow. Active presses back down. Ghost buttons: transparent with border
- StatusBadge: 14% opacity tint of the status color as background, full status color as text. Ultra-restrained, institutional
- Focus states: double ring — 1px inner ring (brand blue) + 4px outer ring (brand blue at 26% opacity)

TOP NAVIGATION BAR (60px height, sticky):
- Background: #152638 with 92% opacity (slight page bleed-through)
- Left: "N" logo mark in #d49a68 (warm copper), then "Netz" wordmark in #f4f7fb
- Center: 7 nav items evenly spaced, 13px semibold:
  Dashboard (active — underline with #84a8d0, text #f4f7fb)
  Screener
  Portfolios
  Risk
  Analytics
  Documents
  Macro
- Right: sun/moon theme toggle button (32×32, rounded, border #345270) + user avatar circle
- Active nav item has 2px bottom border in brand accent. Inactive items use text secondary color
- Navigation fits comfortably in 1440px with no overflow or truncation

PAGE LAYOUT (top to bottom, varying density — the dashboard must NOT be monotonous):

Section 1 — Regime Banner (conditional alert, narrow):
- Full width, compact height (~40px), background: #d6a24a at 12% opacity
- Left: warning icon + "RISK OFF regime detected — VIX elevated, yield curve inverted"
- Right: link "View Macro →"
- This appears only during non-RISK_ON regimes. Show it in the design as an example

Section 2 — Page Header:
- "Wealth OS — Dashboard" title, 24px semibold
- Subtitle below: "2026-03-22 08:47 · Updated" in 13px text muted
- Right side: StatusBadge showing "RISK_OFF" in amber tint

Section 3 — Portfolio Health Hero (DOMINANT — this is the focal point):
- This section should be visually larger and more prominent than everything below it
- 2-column layout: featured portfolio card at 60% width, 2 stacked secondary portfolio cards at 40%
- Featured card (left, taller):
  - Card bg #1a2d44, border #2a3d55, rounded 18px, generous internal padding (28-40px)
  - Kicker label: "CONSERVATIVE" in uppercase muted
  - Large metric: "98.42" in JetBrains Mono 36px — this is NAV
  - Row of 3 sub-metrics below: "CVaR: -2.1%" (green left border), "Sharpe: 1.24" (green), "Regime: RISK_OFF" (amber)
  - CVaR utilization bar: thin horizontal bar showing 65% fill (green zone), with "65% utilized" label
  - Small sparkline chart in top-right corner showing NAV trend (line chart, #84a8d0)
- Secondary cards (right, stacked):
  - Same structure but more compact (16-20px padding)
  - "MODERATE" portfolio: CVaR utilization at 82% (amber), NAV 97.15
  - "AGGRESSIVE" portfolio: CVaR utilization at 94% (red/breach), NAV 95.30, red left border
- The size difference between featured and secondary cards communicates hierarchy — featured portfolio (largest AUM) dominates

Section 4 — NAV Chart (breathing room):
- SectionCard with header "Portfolio NAV History" + period selector pills (1M / 3M / 6M / 1Y / YTD)
- Full-width line chart placeholder area, 200px height, dark card bg
- Three lines representing the three portfolios, using chart palette colors
- X-axis dates, Y-axis NAV values in JetBrains Mono
- This section has standard padding — it provides visual breathing room between the dense hero and the secondary sections below

Section 5 — Drift Alerts + Quick Actions (side by side, denser):
- 60/40 grid split
- Left (60%) "Drift Alerts" SectionCard:
  - Compact internal padding (12-16px)
  - 2 alert rows, each with: instrument name, DTW score, "DTW Drift" badge (outline), "Review" ghost button
  - 1 behavior change alert: red severity badge, anomalous metrics count
  - Dense, tabular feel — these are actionable items
- Right (40%) "Quick Actions" SectionCard:
  - Compact padding
  - List of 3 portfolio quick-links (name + status + chevron →)
  - "Strategic Allocation" shortcut at bottom
  - If a portfolio is in breach status, show red "Action Required" badge next to it

Section 6 — Macro Summary (bottom, high density, reference data):
- SectionCard with header "Macro Summary" + StatusBadge "RISK_OFF"
- Row of 4 metric chips (tight horizontal layout, pill-shaped containers):
  - "VIX: 28.4" (danger-tinted, red text — elevated)
  - "10Y-2Y: -0.42%" (danger-tinted — inverted)
  - "CPI YoY: 3.2%" (warning-tinted)
  - "Fed Funds: 5.25%" (neutral)
- Each chip: rounded-pill shape, status-appropriate 14% opacity tint background, JetBrains Mono for the value
- Minimal padding — this is dense reference data at the bottom

OVERALL DESIGN PRINCIPLES:
- Rhythm must vary: narrow alert → large hero → open chart → dense alerts → dense chips. NOT a parking lot of equal-sized cards
- The portfolio hero section should draw the eye first — it's why the user opened this page
- Cards must be clearly visible against the page background. The #0c1220 → #1a2d44 contrast is the most important visual fix
- All form fields (if any appear) must be darker than their parent card (#0b121c inset bg, #345270 border) — recessed, not floating
- This is an institutional platform — restrained, precise, no playful elements. Think Bloomberg-meets-Linear, not Stripe-meets-Notion
```

---

## Prompt 2 — Dashboard (Light Mode)

```
Design the same "Netz Wealth OS" dashboard from Prompt 1, but in light mode. Desktop 1440×900. Keep identical layout, hierarchy, and content.

LIGHT MODE COLOR CHANGES:
- Page background: subtle gradient from #edf2f7 blended with 42% #e6edf6 at top, fading to #f4f7fb at 220px — a soft brand-tinted wash that differentiates light mode from dark
- Card surfaces: #ffffff (pure white, clear elevation against blue-gray bg)
- Card surface alternate: #edf2f7
- Elevated surfaces: #fbfcfe
- Inset surfaces (form fields): #e7edf4
- Borders: #d6deea (subtle), #c5d0de (standard), #aab8cb (strong)
- Text primary: #122033
- Text secondary: #48586b
- Text muted: #6f7f93
- Brand accent: #18324d (dark navy — links, active states)
- Brand highlight: #c58757 (warm orange — logo, occasional accent)
- Success: #0f8f70
- Warning: #b7791f
- Danger: #c15766
- Info: #316cc4
- Shadows: standard multi-layer shadows are visible in light mode — cards get "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)" plus a subtle inset highlight "inset 0 1px 0 rgba(255,255,255,0.85)"

EVERYTHING ELSE identical to Prompt 1:
- Same 7-item nav bar, same layout hierarchy, same content, same component styling rules
- Nav bar background: white with bottom border #d6deea
- MetricCard left accent borders, StatusBadge 14% tint, JetBrains Mono for data — all same
- The gradient page background is the key differentiator — light mode should feel visibly different from dark mode at a glance, with the subtle blue-tinted top wash giving it a branded feel
```

---

## Prompt 3 — Unified Screener (Dark Mode, 5 Tabs)

```
Design a "Screener" page for "Netz Wealth OS" in dark mode. Desktop 1440×900. This is the central hub for all investment entity discovery — it consolidates what were previously 5 separate pages into one tabbed interface.

USE THE SAME DARK MODE COLOR SYSTEM FROM PROMPT 1 (all hex values identical).

TOP NAVIGATION: Same 7-item nav bar. "Screener" is the active item (underlined, bright text).

PAGE HEADER:
- Title: "Screener" (24px semibold)
- Right side: "Run Screening" primary button (filled #84a8d0 bg, dark text)

TAB BAR (immediately below header):
- 5 tabs in a horizontal row, using the PageTabs component pattern:
  Screening | Funds | Managers | Instruments | Universe
- Active tab: text #f4f7fb, 2px bottom border #84a8d0, font-weight 600
- Inactive tabs: text #8d9caf, no border, font-weight 500
- Tab bar has a subtle bottom border #2a3d55 spanning full width

SHOW THE "Screening" TAB AS ACTIVE, with this content:

Left sidebar — Screening Funnel (240px width):
- Card bg #1a2d44, full height of content area
- Header: "Screening Funnel" kicker label
- 3 funnel stages stacked vertically, connected by thin vertical lines:
  - "Universe" → count badge "1,247" (neutral)
  - "L1: Eliminatory" → count badge "1,031 passed" (green tint) + "216 failed" (red tint)
  - "L2: Mandate Fit" → count badge "894 passed" + "137 failed"
  - "L3: Quantitative" → count badge "612 passed" + "282 failed"
- The funnel visually narrows (each stage has a slightly shorter bar or smaller icon)
- Below funnel: "Latest Run" info — "2026-03-21 14:30" + "1,247 instruments" in muted text

Main content area — Results Table:
- Status tabs above table: All (1247) | PASS (612) | WATCHLIST (143) | FAIL (492)
  - "All" is active (underlined)
- DataTable with columns:
  Name | ISIN | Ticker | Type | Score | Status | Layer Failed | Screened At
- 8-10 rows of sample data with:
  - Status shown as StatusBadge: PASS (green tint), FAIL (red tint), WATCHLIST (amber tint)
  - Score in JetBrains Mono
  - Type column: "fund", "bond", "equity" as subtle badges
  - Layer Failed: "L1", "L2", "L3", or "—" for PASS
- Table styling: alternating row backgrounds (#1a2d44 and #152638), header row in #0b121c, text 13px
- Row hover: bg shifts to #243a52

Right side — Context Panel (collapsed indicator):
- A subtle vertical edge/handle on the right side of the table suggesting a slide-out detail panel
- When a row is selected, this panel slides out showing instrument detail (show it collapsed in this frame)

CUSTOM SELECT COMPONENT (shown in funnel sidebar filter dropdowns):
- Instead of native browser selects, show a custom trigger button:
  - Rectangular field with #0b121c background (inset/recessed), #345270 border, rounded 10px
  - Text showing selected value left-aligned
  - Chevron-down icon (▾) on the right side, in #8d9caf color
  - The chevron is the critical affordance — users must see that this is a dropdown
- Show one dropdown in its OPEN state as a design reference:
  - Dropdown panel floats below the trigger, bg #243a52, border #345270, rounded 14px, shadow
  - List of options with hover state (#2a3d55 bg), selected option has a checkmark icon
  - If searchable: show a search input at the top of the dropdown (inset bg, magnifying glass icon)
```

---

## Prompt 4 — Screener "Funds" Tab (Dark Mode)

```
Design the "Funds" tab of the Screener page for "Netz Wealth OS" in dark mode. Desktop 1440×900. Same color system and nav bar as previous prompts.

PAGE HEADER: "Screener" title. Same 5-tab bar, but now "Funds" tab is active (underlined, bright text).

CONTENT — Fund Universe with DD Pipeline Status:

Filter row (above table):
- Horizontal row of filter controls:
  - Search input: inset bg #0b121c, border #345270, placeholder "Search by name, manager, ISIN...", magnifying glass icon left
  - Strategy dropdown (custom select with chevron): "All Strategies ▾"
  - Status dropdown: "All Statuses ▾"
  - DD Status dropdown: "All DD Statuses ▾"
- Each dropdown uses the custom select component (NOT native browser select): rectangular with visible chevron-down icon on the right

DataTable:
- Columns: Name | Manager | Strategy | AUM | Status | DD Report | Score | Last Updated
- 10 rows of realistic institutional fund data:
  - Fund names like "Bridgewater All Weather", "Renaissance Medallion", "AQR Momentum"
  - Manager names: "Bridgewater Associates", "Renaissance Technologies", "AQR Capital"
  - Strategy: "Global Macro", "Quant", "Long/Short Equity", "Credit", "Multi-Strategy"
  - AUM in JetBrains Mono: "$42.3B", "$12.1B", "$8.7B"
  - Status as StatusBadge: "Approved" (green), "Pending" (amber), "Watchlist" (amber outline)
  - DD Report status: "Complete" (green), "In Progress" (blue), "Not Started" (muted outline)
  - Score: numeric 0-100 in JetBrains Mono, colored by range (>80 green, 60-80 amber, <60 red)
- Sort indicator on "AUM" column (downward arrow, sorted descending)
- Pagination at bottom: "Showing 1-10 of 847" + page navigation

Status tabs above table:
- All (847) | Approved (312) | DD Pending (198) | Watchlist (87) | New (250)
- "All" active

EMPTY STATE REFERENCE (show as a separate small frame):
- When no funds match filters, show:
  - Dashed border container (1px dashed #2a3d55), rounded 14px, centered content
  - Document icon (outline style, #8d9caf)
  - Title: "No funds match your filters" (16px semibold, text primary)
  - Description: "Try adjusting your search criteria or strategy filter." (14px, text muted)
  - Button: "Clear Filters" (ghost button, border #345270)
```

---

## Prompt 5 — Component Reference Sheet (Dark + Light)

```
Design a component reference sheet for "Netz Wealth OS" design system. Split the frame vertically: left half is dark mode, right half is light mode. Frame size 1920×1080.

Title at top center: "Netz Design System — Component Reference" in 20px semibold

FOR EACH SIDE (dark left, light right), show these components:

SECTION 1 — Form Controls:
Row 1: Text input (empty with placeholder), Text input (filled with value "Bridgewater"), Text input (focused — double ring: 1px #84a8d0 inner + 4px 26% opacity outer)
Row 2: Custom Select (closed, showing "All Strategies ▾" with visible chevron-down icon), Custom Select (open state — dropdown visible with 5 options, one highlighted on hover, one checked)
Row 3: Textarea (3 lines, with character counter "124/500")

Dark mode form fields: bg #0b121c (inset), border #345270, text #f4f7fb, placeholder #8d9caf
Light mode form fields: bg #e7edf4 (inset), border #c5d0de, text #122033, placeholder #6f7f93

SECTION 2 — MetricCards:
Row of 3 MetricCards side by side:
- "CVaR 95" — value "-2.1%" in JetBrains Mono 28px — green 3px left border — delta arrow up "+0.3%" with period "1M" — utilization bar at 65% (green)
- "Sharpe Ratio" — value "1.24" — amber 3px left border (warning) — delta arrow down "-0.08" — no utilization bar
- "NAV" — value "98.42" — red 3px left border (breach) — delta flat "0.00" — sparkline mini chart in top-right corner

SECTION 3 — StatusBadges:
Row: PASS (14% green bg, green text), WATCHLIST (14% amber bg, amber text), FAIL (14% red bg, red text), RISK_OFF (14% amber bg), IN PROGRESS (14% blue bg), APPROVED (14% green bg)

SECTION 4 — Buttons:
Row: Primary (filled #84a8d0 dark/#18324d light bg), Secondary (ghost, border), Destructive (red-tinted), Disabled (muted, 50% opacity), Small size, Loading state (spinner icon)
Show hover state for primary: 1px lift with deeper shadow

SECTION 5 — Cards & Surfaces:
- Card (standard): bg elevated, 1px border subtle, shadow, rounded 14px, sample content inside
- SectionCard (collapsible): header with 4% brand tint bg, chevron rotation icon, title "Drift Alerts", expand/collapse state
- Card with status accent: same card but 3px left border in green (ok status)

SECTION 6 — Empty States:
- Zero state: dashed border container, centered document icon, title "No portfolios configured", description "Create your first model portfolio to see performance metrics.", button "Create Portfolio"
- Filtered-empty state: dashed border, funnel icon, "No results match your filters", "Clear Filters" button
- Loading state: same container shape but filled with skeleton pulse animation bars (3 horizontal lines at 60%, 80%, 40% width, subtle pulse animation indicated with gradient overlay)

SECTION 7 — Navigation:
- TopNav bar showing 7 items: Dashboard, Screener, Portfolios, Risk, Analytics, Documents, Macro
- Show "Screener" as active (underline + bright text)
- Theme toggle button at right (sun icon for dark side, moon icon for light side)
- Below: PageTabs showing 5 tabs: Screening (active) | Funds | Managers | Instruments | Universe
- Below: Breadcrumb: "Screener / Funds / Bridgewater All Weather" with links on ancestors

SECTION 8 — Data Table:
- 5 rows of sample data with alternating row backgrounds
- Header: dark inset bg, uppercase kicker labels
- Cells: 13px, numbers in JetBrains Mono
- One row in hover state (lighter bg)
- One row selected (brand accent at 10% bg tint)
- Sort indicator on one column header (arrow icon)
- Pagination bar below: "1-10 of 847" + page buttons

COLOR SWATCHES at bottom:
Show the full token palette as labeled color squares:
Dark side: #0c1220 "Surface" → #152638 "Alt" → #1a2d44 "Elevated" → #243a52 "Raised" → #0b121c "Inset"
Light side: #f4f7fb "Surface" → #edf2f7 "Alt" → #ffffff "Elevated" → #fbfcfe "Raised" → #e7edf4 "Inset"
Plus: border swatches, text color swatches, semantic color swatches, chart palette swatches
```

---

## Prompt 6 — Screener "Managers" Tab (Dark Mode)

```
Design the "Managers" tab of the Screener page for "Netz Wealth OS" in dark mode. Desktop 1440×900. Same color system and nav as previous prompts.

TAB BAR: 5 tabs, "Managers" active. This tab is the SEC manager discovery and monitoring view.

CONTENT:

Filter row:
- Search: "Search managers by name, CIK, location..."
- Dropdowns (custom select with chevrons): "Strategy ▾", "AUM Range ▾", "Region ▾"
- Toggle: "Watchlist Only" (toggle switch, off state)

Manager cards grid (3 columns):
Show 6 manager cards in a 3×2 grid:
Each card (bg #1a2d44, border #2a3d55, rounded 14px):
- Header: Manager name (16px semibold) + "CIK: 1234567" in muted text
- Row: "AUM: $42.3B" | "Strategy: Global Macro" | "Location: Westport, CT"
- Row: "13F Holdings: 1,247" | "Latest Filing: 2026-03-15"
- Bottom row: status badges — "ADV Current" (green), "N-PORT Available" (blue), or "Stale Filing" (amber)
- "View Detail →" link in brand accent color

One card should show an "Added to Watchlist" state: subtle #84a8d0 left border + filled star icon in the header

Below cards: "Showing 6 of 2,341 managers" + pagination
```

---

## Usage Notes

- Generate prompts 1-5 as priority (dashboard both modes + screener + components)
- Prompt 6 is supplementary for the manager screener tab
- All prompts share the same design system — the color hex values are consistent across all frames
- The critical visual fixes being validated: dark mode contrast, select chevrons, 7-item nav, dashboard hierarchy, empty states, form field visibility
