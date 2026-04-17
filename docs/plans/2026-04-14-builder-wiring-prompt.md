# Session 1: Builder Command Panel — Wiring & Polishing (Svelte 5)

## CONTEXT
The Portfolio Builder (`/portfolio/builder`) is already migrated to the new 2-column Terminal layout with Svelte 5 runes. The right column (Results Panel) has its tabs and logic in place. However, the left column (Command Panel) is missing two critical integrations:
1. `RegimeContextStrip.svelte` (Zone A) exists but is not mounted in `+page.svelte`.
2. `CalibrationPanel.svelte` (Zone B) holds a local `draft` calibration, but does not show the PM what changed compared to the *last constructed run*. Institutional PMs need to see deltas (e.g., "Tail loss budget is currently 5%, was 10% in last run").

## OBJECTIVE
1. Integrate `RegimeContextStrip` into `+page.svelte` (Zone A).
2. Enhance the `CalibrationPanel` and its field components to accept and display an `originalValue` (derived from the last run's calibration snapshot) to provide clear delta visibility.

## CONSTRAINTS
- **Svelte 5 Runes Only**: Use `$props`, `$derived`, `$effect`. No `export let` or `$:`.
- **Zero Mocks**: Read the last run snapshot directly from `workspace.constructionRun?.calibration_snapshot`.
- **Institutional Formatters**: Any displayed `originalValue` must be formatted using `@investintell/ui` formatters (e.g., `formatPercent`, `formatNumber`), exactly like the primary `value`.
- **Draft Logic**: Do not break the existing `draft` clone/patch logic in `CalibrationPanel.svelte`. Deltas should compare the *current draft* against the *last run snapshot*.

## DELIVERABLES

**1. `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte`**
- Import `RegimeContextStrip` from `$lib/components/terminal/builder/RegimeContextStrip.svelte`.
- Insert `<RegimeContextStrip regimeBands={workspace.regimeBands} />` immediately below the `.builder-portfolio-select` div and above the `.builder-calibration` div.

**2. `frontends/wealth/src/lib/components/portfolio/CalibrationSliderField.svelte`** (and related fields)
- Add an optional `originalValue: number | null` (or appropriate type) to the `Props` interface.
- If `originalValue` is provided and differs from `value`, display a small indicator next to the current value (e.g., `<span class="csf-original">was {formattedOriginal}</span>`).
- Update `CalibrationSelectField.svelte` and `CalibrationToggleField.svelte` with similar logic.

**3. `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte`**
- Create a `$derived` variable that extracts the last run's snapshot: `const snapshot = workspace.constructionRun?.calibration_snapshot;`
- Pass the corresponding `originalValue` to each field. For example: `originalValue={snapshot?.cvar_limit as number | undefined}`.
- Ensure the Expert tier also indicates changed rows if possible, or just focus on Basic/Advanced fields.

## VERIFICATION
- Run `make check-all` or `pnpm --filter investintell-wealth check`. It must pass without type errors.
- Ensure Svelte 5 `$props` syntax is correct in all modified components.
- The UI should not crash if `workspace.constructionRun` is null (empty state).

## ANTI-PATTERNS
- Do not use `new Intl.NumberFormat()` — use `@investintell/ui`.
- Do not mutate `workspace.constructionRun` — it is read-only state.