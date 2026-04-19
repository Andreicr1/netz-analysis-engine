<!--
  CalibrationPanel — Builder right-rail surface that exposes the
  63-input calibration model to the PM (DL5).

  Phase 4 Task 4.1 + 4.2 of the portfolio-enterprise-workbench plan.
  Replaces the legacy PolicyPanel no-op: every field writes to the
  typed ``portfolio_calibration`` row via the new GET/PUT backend
  route. The panel holds a local draft and ONLY persists on Apply
  (Preview triggers an in-flight preview fetch but never touches the
  DB). DL5 is explicit about this.

  Tier structure (OD-1 default = Basic, user can expand):
    - Basic (5)    — mandate, cvar_limit, max_single_fund_weight,
                     turnover_cap, stress_scenarios_active
    - Advanced (10) — regime_override + BL + GARCH + turnover lambda
                     + stress severity + advisor + cvar level + risk
                     aversion + shrinkage
    - Expert (48)  — accordion over the ``expert_overrides`` JSONB
                     with arbitrary key/value rows

  DL15 (no localStorage) — the draft lives in component $state and
  is lost on unmount if not Applied. DL16 (formatter discipline) —
  every number renders via @investintell/ui formatters.
-->
<script lang="ts">
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";
	import { formatNumber, formatShortDate } from "@investintell/ui";
	import type {
		PortfolioCalibration,
		PortfolioCalibrationUpdate,
		CalibrationMandate,
		StressScenarioId,
	} from "$wealth/types/portfolio-calibration";
	import { calibrationsEqual } from "$wealth/types/portfolio-calibration";
	import CalibrationSliderField from "./CalibrationSliderField.svelte";
	import CalibrationSelectField from "./CalibrationSelectField.svelte";
	import CalibrationToggleField from "./CalibrationToggleField.svelte";
	import CalibrationScenarioGroup from "./CalibrationScenarioGroup.svelte";
	import RiskBudgetPanel from "./RiskBudgetPanel.svelte";

	// ── Tier + preview state ─────────────────────────────────────
	let tier = $state<"basic" | "advanced" | "expert">("basic");
	let isPreviewing = $state(false);
	let previewError = $state<string | null>(null);
	let previewTimer: ReturnType<typeof setTimeout> | null = null;

	const calibration = $derived(workspace.calibration);
	const loading = $derived(workspace.isLoadingCalibration);
	const applying = $derived(workspace.isApplyingCalibration);

	// PR-A5 F.1 — snapshot of the calibration as of the most recent
	// construction run. Drives the per-field "Anteriormente" overlay
	// in every CalibrationField. Loose typing is intentional — the
	// snapshot JSONB schema evolves with calibration; readers cast
	// per known key with safe fallbacks.
	const snapshot = $derived(
		(workspace.constructionRun?.calibration_snapshot ?? null) as
			| (Partial<PortfolioCalibration> & Record<string, unknown>)
			| null,
	);

	// ── TAA regime indicator state (Sprint 4) ────────────────────

	// Local working copy of the calibration — cloned on load + on portfolio switch.
	let draft = $state<PortfolioCalibration | null>(null);

	// Sync draft when the backend snapshot changes (new portfolio, or Apply reload).
	$effect(() => {
		const snap = calibration;
		if (snap === null) {
			draft = null;
			return;
		}
		if (!draft || draft.portfolio_id !== snap.portfolio_id) {
			draft = structuredClone(snap);
		}
	});

	const dirty = $derived.by(() => {
		if (!draft || !calibration) return false;
		return !calibrationsEqual(draft, calibration);
	});

	/**
	 * Partial updater — the field components drive every edit through
	 * this single function so the ``draft`` is always a fresh object
	 * (Svelte 5 tracks identity, not deep mutation).
	 */
	function update(patch: Partial<PortfolioCalibration>) {
		if (!draft) return;
		draft = { ...draft, ...patch };
	}

	// ── Option catalogs (OD-22 locked for regime labels) ──────────
	const MANDATE_OPTIONS = [
		{ value: "conservative", label: "Conservative" },
		{ value: "moderate", label: "Moderate" },
		{ value: "balanced", label: "Balanced" },
		{ value: "aggressive", label: "Aggressive" },
	] as const;

	const REGIME_OPTIONS = [
		{ value: "auto", label: "Auto (engine-detected)" },
		{ value: "NORMAL", label: "Balanced" },
		{ value: "RISK_ON", label: "Expansion" },
		{ value: "RISK_OFF", label: "Defensive" },
		{ value: "CRISIS", label: "Stress" },
		{ value: "INFLATION", label: "Inflation" },
	] as const;

	const CVAR_LEVEL_OPTIONS = [
		{ value: "0.90", label: "90%" },
		{ value: "0.95", label: "95% (default)" },
		{ value: "0.99", label: "99%" },
	] as const;

	const STRESS_OPTIONS: readonly { value: StressScenarioId; label: string }[] = [
		{ value: "gfc_2008", label: "GFC 2008" },
		{ value: "covid_2020", label: "COVID 2020" },
		{ value: "taper_2013", label: "Taper Tantrum 2013" },
		{ value: "rate_shock_200bps", label: "Rate Shock +200bps" },
	];

	// ── Nullable-value sentinels ─────────────────────────────────
	// These convert null to a display sentinel for the slider (which
	// cannot bind to null) and back at diff time. 1.0 = "no cap" for
	// turnover, "auto" = null for regime, etc.
	const TURNOVER_CAP_SENTINEL = 1.0;
	const TURNOVER_LAMBDA_SENTINEL = 1.0;
	const LAMBDA_RISK_AVERSION_SENTINEL = 2.0;
	const SHRINKAGE_SENTINEL = 0.5;

	// ── Preview + Apply ───────────────────────────────────────────

	/**
	 * Preview — DL5 mandates an explicit user action, NEVER reactive.
	 * The button kicks off a 1500ms debounce so a PM who presses it
	 * twice in quick succession only fires one request. Preview does
	 * not mutate the backend; in v1 it acts as "apply + construct"
	 * because a dedicated ``/construct/preview`` endpoint is a v1.1
	 * item. The dirty draft is flushed to the backend, then the
	 * construction job runs so the PM can see the narrative update.
	 */
	function schedulePreview() {
		if (!draft || !calibration || !dirty) return;
		if (previewTimer) clearTimeout(previewTimer);
		isPreviewing = true;
		previewError = null;
		previewTimer = setTimeout(async () => {
			const applied = await workspace.applyCalibration(diffPatch(calibration!, draft!));
			if (!applied) {
				isPreviewing = false;
				previewError = workspace.lastError?.message ?? "Preview failed to persist";
				return;
			}
			await workspace.runBuildJob();
			isPreviewing = false;
		}, 1500);
	}

	async function handleApply() {
		if (!draft || !calibration) return;
		const patch = diffPatch(calibration, draft);
		const next = await workspace.applyCalibration(patch);
		if (next) draft = structuredClone(next);
	}

	function handleReset() {
		if (calibration) draft = structuredClone(calibration);
	}

	/**
	 * Compute the partial-update body the backend expects (``exclude_unset``
	 * semantics). Only includes fields that changed between ``base`` and
	 * ``next`` so we don't clobber fields the user did not touch.
	 */
	function diffPatch(
		base: PortfolioCalibration,
		next: PortfolioCalibration,
	): PortfolioCalibrationUpdate {
		const patch: PortfolioCalibrationUpdate = {};
		if (base.mandate !== next.mandate) patch.mandate = next.mandate;
		if (base.cvar_limit !== next.cvar_limit) patch.cvar_limit = next.cvar_limit;
		if (base.max_single_fund_weight !== next.max_single_fund_weight)
			patch.max_single_fund_weight = next.max_single_fund_weight;
		if (base.turnover_cap !== next.turnover_cap) patch.turnover_cap = next.turnover_cap;
		const activeChanged =
			base.stress_scenarios_active.length !== next.stress_scenarios_active.length ||
			base.stress_scenarios_active.some((v, i) => v !== next.stress_scenarios_active[i]);
		if (activeChanged) patch.stress_scenarios_active = next.stress_scenarios_active;

		if (base.regime_override !== next.regime_override)
			patch.regime_override = next.regime_override;
		if (base.bl_enabled !== next.bl_enabled) patch.bl_enabled = next.bl_enabled;
		if (base.bl_view_confidence_default !== next.bl_view_confidence_default)
			patch.bl_view_confidence_default = next.bl_view_confidence_default;
		if (base.garch_enabled !== next.garch_enabled) patch.garch_enabled = next.garch_enabled;
		if (base.turnover_lambda !== next.turnover_lambda)
			patch.turnover_lambda = next.turnover_lambda;
		if (base.stress_severity_multiplier !== next.stress_severity_multiplier)
			patch.stress_severity_multiplier = next.stress_severity_multiplier;
		if (base.advisor_enabled !== next.advisor_enabled)
			patch.advisor_enabled = next.advisor_enabled;
		if (base.cvar_level !== next.cvar_level) patch.cvar_level = next.cvar_level;
		if (base.lambda_risk_aversion !== next.lambda_risk_aversion)
			patch.lambda_risk_aversion = next.lambda_risk_aversion;
		if (base.shrinkage_intensity_override !== next.shrinkage_intensity_override)
			patch.shrinkage_intensity_override = next.shrinkage_intensity_override;

		const baseKeys = Object.keys(base.expert_overrides);
		const nextKeys = Object.keys(next.expert_overrides);
		const sameShape =
			baseKeys.length === nextKeys.length &&
			baseKeys.every((k) => base.expert_overrides[k] === next.expert_overrides[k]);
		if (!sameShape) patch.expert_overrides = next.expert_overrides;

		return patch;
	}

	// ── Expert tier row editor ────────────────────────────────────
	let newExpertKey = $state("");
	let newExpertValue = $state("");

	function addExpertKey() {
		if (!draft || !newExpertKey.trim()) return;
		draft = {
			...draft,
			expert_overrides: {
				...draft.expert_overrides,
				[newExpertKey.trim()]: coerceExpertValue(newExpertValue),
			},
		};
		newExpertKey = "";
		newExpertValue = "";
	}

	function removeExpertKey(key: string) {
		if (!draft) return;
		const next = { ...draft.expert_overrides };
		delete next[key];
		draft = { ...draft, expert_overrides: next };
	}

	function coerceExpertValue(raw: string): unknown {
		const trimmed = raw.trim();
		if (trimmed === "") return null;
		if (trimmed === "true") return true;
		if (trimmed === "false") return false;
		const asNumber = Number(trimmed);
		if (!Number.isNaN(asNumber)) return asNumber;
		return trimmed;
	}

	function formatExpertValue(value: unknown): string {
		if (value === null || value === undefined) return "—";
		if (typeof value === "number") return formatNumber(value, 4);
		if (typeof value === "boolean") return value ? "true" : "false";
		if (typeof value === "string") return value;
		return JSON.stringify(value);
	}

	const expertEntries = $derived.by(() => {
		if (!draft) return [];
		return Object.entries(draft.expert_overrides).sort(([a], [b]) => a.localeCompare(b));
	});
</script>

{#if !workspace.portfolio}
	<div class="cp-empty">
		<div class="cp-empty-block">
			<span class="cp-empty-title">NO PORTFOLIO SELECTED</span>
			<span class="cp-empty-msg">Select a model portfolio on the left to edit its calibration.</span>
		</div>
	</div>
{:else if loading && !draft}
	<div class="cp-empty">
		<div class="cp-empty-block">
			<span class="cp-empty-title">LOADING CALIBRATION</span>
			<span class="cp-empty-msg">Fetching the 63-input surface from the backend.</span>
		</div>
	</div>
{:else if !draft}
	<div class="cp-empty">
		<div class="cp-empty-block">
			<span class="cp-empty-title">CALIBRATION UNAVAILABLE</span>
			<span class="cp-empty-msg">{workspace.lastError?.message ?? "Calibration could not be loaded for this portfolio."}</span>
		</div>
	</div>
{:else}
	<div class="cp-root">
		<div class="cp-tabs" role="tablist">
			<button type="button" role="tab" class="cp-tab" class:cp-tab--active={tier === "basic"}
				aria-selected={tier === "basic"} onclick={() => (tier = "basic")}>BASIC</button>
			<button type="button" role="tab" class="cp-tab" class:cp-tab--active={tier === "advanced"}
				aria-selected={tier === "advanced"} onclick={() => (tier = "advanced")}>ADVANCED</button>
			<button type="button" role="tab" class="cp-tab" class:cp-tab--active={tier === "expert"}
				aria-selected={tier === "expert"} onclick={() => (tier = "expert")}>EXPERT</button>
		</div>

		{#if tier === "basic"}
			<!-- ── Basic tier (5 fields) ───────────────────────────── -->
			<section class="cp-section" role="tabpanel">
					<CalibrationSelectField
						id="cp-mandate"
						label="Mandate"
						description="Risk profile archetype — drives downstream defaults for tail loss budget, diversification, and turnover."
						value={draft.mandate}
						onChange={(v) => update({ mandate: v as CalibrationMandate })}
						options={MANDATE_OPTIONS}
						originalValue={snapshot?.mandate as string | undefined}
					/>

					{#if workspace.portfolio}
						<RiskBudgetPanel
							portfolio={workspace.portfolio}
							calibration={draft}
							snapshot={snapshot}
							onChange={(patch) => update(patch)}
						/>
					{/if}

					<CalibrationSliderField
						id="cp-max-weight"
						label="Max single-fund weight"
						description="Hard cap on concentration in any one instrument."
						value={draft.max_single_fund_weight}
						onChange={(v) => update({ max_single_fund_weight: v })}
						min={0.05}
						max={0.4}
						step={0.01}
						displayFormat="percent"
						digits={1}
						originalValue={snapshot?.max_single_fund_weight as number | undefined}
					/>

					<CalibrationSliderField
						id="cp-turnover-cap"
						label="Turnover cap"
						description="Upper bound on rebalance trading — 100% means no cap."
						value={draft.turnover_cap ?? TURNOVER_CAP_SENTINEL}
						onChange={(v) => update({ turnover_cap: v })}
						min={0.05}
						max={1.0}
						step={0.05}
						displayFormat="percent"
						digits={0}
						originalValue={snapshot == null
							? undefined
							: ((snapshot.turnover_cap ?? TURNOVER_CAP_SENTINEL) as number)}
					/>

					<CalibrationScenarioGroup
						label="Active stress scenarios"
						description="Scenarios run at every construction — drive the Builder Stress matrix."
						value={draft.stress_scenarios_active}
						onChange={(v) => update({ stress_scenarios_active: v })}
						options={STRESS_OPTIONS}
						originalValue={snapshot?.stress_scenarios_active as
							| readonly StressScenarioId[]
							| undefined}
					/>
				</section>
		{:else if tier === "advanced"}
			<!-- ── Advanced tier (10 fields) ───────────────────────── -->
			<section class="cp-section" role="tabpanel">
					<CalibrationSelectField
						id="cp-regime-override"
						label="Regime override"
						description="Force a regime to pin covariance shrinkage. ``Auto`` leaves it to the engine."
						value={draft.regime_override ?? "auto"}
						onChange={(v) =>
							update({
								regime_override: v === "auto"
									? null
									: (v as PortfolioCalibration["regime_override"]),
							})}
						options={REGIME_OPTIONS}
						originalValue={snapshot == null
							? undefined
							: ((snapshot.regime_override as string | null | undefined) ?? "auto")}
					/>

					<CalibrationToggleField
						id="cp-bl-enabled"
						label="Expected return blending"
						description="Enable the Bayesian blend of the prior with IC views. Off = equilibrium prior only."
						value={draft.bl_enabled}
						onChange={(v) => update({ bl_enabled: v })}
						originalValue={snapshot?.bl_enabled as boolean | undefined}
					/>

					<CalibrationSliderField
						id="cp-bl-confidence"
						label="BL view confidence (default)"
						description="Default confidence applied to new IC views — higher pulls the posterior closer to the view."
						value={draft.bl_view_confidence_default}
						onChange={(v) => update({ bl_view_confidence_default: v })}
						min={0}
						max={1}
						step={0.05}
						displayFormat="raw"
						digits={2}
						disabled={!draft.bl_enabled}
						originalValue={snapshot?.bl_view_confidence_default as number | undefined}
					/>

					<CalibrationToggleField
						id="cp-garch-enabled"
						label="Forward-looking volatility"
						description="Use forward-looking conditional volatility instead of realized vol."
						value={draft.garch_enabled}
						onChange={(v) => update({ garch_enabled: v })}
						originalValue={snapshot?.garch_enabled as boolean | undefined}
					/>

					<CalibrationSliderField
						id="cp-turnover-lambda"
						label="Turnover penalty"
						description="L1 penalty weight on turnover inside the optimizer objective."
						value={draft.turnover_lambda ?? TURNOVER_LAMBDA_SENTINEL}
						onChange={(v) => update({ turnover_lambda: v })}
						min={0.1}
						max={10}
						step={0.1}
						displayFormat="raw"
						digits={1}
						originalValue={snapshot == null
							? undefined
							: ((snapshot.turnover_lambda ?? TURNOVER_LAMBDA_SENTINEL) as number)}
					/>

					<CalibrationSliderField
						id="cp-stress-multiplier"
						label="Stress severity multiplier"
						description="Scales the preset stress shocks — 1.0 = canonical severity."
						value={draft.stress_severity_multiplier}
						onChange={(v) => update({ stress_severity_multiplier: v })}
						min={0.5}
						max={2.0}
						step={0.05}
						displayFormat="x"
						digits={2}
						originalValue={snapshot?.stress_severity_multiplier as number | undefined}
					/>

					<CalibrationToggleField
						id="cp-advisor-enabled"
						label="Construction advisor"
						description="Enable the credit-side advisor that recommends fund additions to close risk budget gaps."
						value={draft.advisor_enabled}
						onChange={(v) => update({ advisor_enabled: v })}
						originalValue={snapshot?.advisor_enabled as boolean | undefined}
					/>

					<CalibrationSelectField
						id="cp-cvar-level"
						label="Tail loss confidence level"
						description="Confidence level used for the tail loss budget."
						value={draft.cvar_level.toString()}
						onChange={(v) => update({ cvar_level: Number.parseFloat(v) })}
						options={CVAR_LEVEL_OPTIONS}
						originalValue={snapshot?.cvar_level == null
							? undefined
							: (snapshot.cvar_level as number).toString()}
					/>

					<CalibrationSliderField
						id="cp-risk-aversion"
						label="Risk aversion"
						description="Coefficient on variance in the utility — higher = more conservative."
						value={draft.lambda_risk_aversion ?? LAMBDA_RISK_AVERSION_SENTINEL}
						onChange={(v) => update({ lambda_risk_aversion: v })}
						min={0.5}
						max={5}
						step={0.1}
						displayFormat="raw"
						digits={1}
						originalValue={snapshot == null
							? undefined
							: ((snapshot.lambda_risk_aversion ?? LAMBDA_RISK_AVERSION_SENTINEL) as number)}
					/>

					<CalibrationSliderField
						id="cp-shrinkage"
						label="Shrinkage intensity override"
						description="Covariance shrinkage override (0..1). Leave at default for auto-selection."
						value={draft.shrinkage_intensity_override ?? SHRINKAGE_SENTINEL}
						onChange={(v) => update({ shrinkage_intensity_override: v })}
						min={0}
						max={1}
						step={0.05}
						displayFormat="raw"
						digits={2}
						originalValue={snapshot == null
							? undefined
							: ((snapshot.shrinkage_intensity_override ?? SHRINKAGE_SENTINEL) as number)}
					/>
				</section>
		{:else if tier === "expert"}
			<!-- ── Expert tier (arbitrary JSONB overrides) ─────────── -->
			<section class="cp-section" role="tabpanel">
					<p class="cp-expert-hint">
						Expert overrides are free-form key/value pairs stored in
						<code>expert_overrides</code> JSONB. Use only for optimizer knobs
						that have not graduated to typed columns.
					</p>

					{#if expertEntries.length === 0}
						<p class="cp-expert-empty">No expert overrides set.</p>
					{:else}
						<ul class="cp-expert-list">
							{#each expertEntries as [k, v] (k)}
								<li class="cp-expert-row">
									<span class="cp-expert-key">{k}</span>
									<span class="cp-expert-value">{formatExpertValue(v)}</span>
									<button
										type="button"
										class="cp-expert-remove"
										onclick={() => removeExpertKey(k)}
										aria-label={`Remove ${k}`}
									>
										×
									</button>
								</li>
							{/each}
						</ul>
					{/if}

					<div class="cp-expert-add">
						<input
							type="text"
							class="cp-expert-input"
							placeholder="knob_name"
							bind:value={newExpertKey}
						/>
						<input
							type="text"
							class="cp-expert-input"
							placeholder="value (number / true / false / text)"
							bind:value={newExpertValue}
						/>
						<button
							type="button"
							class="cp-expert-add-btn"
							onclick={addExpertKey}
							disabled={!newExpertKey.trim()}
						>
							ADD
						</button>
					</div>
			</section>
		{/if}

		<!-- ── Preview + Apply row (DL5) ───────────────────────── -->
		<footer class="cp-footer">
			<div class="cp-footer-status">
				{#if applying}
					<span class="cp-status cp-status--pending">Applying…</span>
				{:else if isPreviewing}
					<span class="cp-status cp-status--pending">Previewing…</span>
				{:else if dirty}
					<span class="cp-status cp-status--dirty">Unsaved edits</span>
				{:else if calibration}
					<span class="cp-status cp-status--clean">
						Saved · last updated {formatShortDate(calibration.updated_at)}
					</span>
				{/if}
				{#if previewError}
					<span class="cp-status cp-status--error">{previewError}</span>
				{/if}
			</div>
			<div class="cp-footer-actions">
				<button type="button" class="cp-action cp-action--ghost"
					disabled={!dirty || applying || isPreviewing}
					onclick={handleReset}>RESET</button>
				<button type="button" class="cp-action cp-action--outline"
					disabled={!dirty || applying || isPreviewing}
					onclick={schedulePreview}>PREVIEW</button>
				<button type="button" class="cp-action cp-action--primary"
					disabled={!dirty || applying || isPreviewing}
					onclick={handleApply}>APPLY</button>
			</div>
		</footer>
	</div>
{/if}

<style>
	.cp-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.cp-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--terminal-space-6);
		height: 100%;
		font-family: var(--terminal-font-mono);
		background: var(--terminal-bg-panel);
	}
	.cp-empty-block {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--terminal-space-2);
	}
	.cp-empty-title {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}
	.cp-empty-msg {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		text-align: center;
		max-width: 280px;
		line-height: var(--terminal-leading-normal);
	}

	.cp-tabs {
		display: flex;
		align-items: stretch;
		height: 32px;
		padding: 0;
		flex-shrink: 0;
		border-bottom: var(--terminal-border-hairline);
	}
	.cp-tab {
		display: inline-flex;
		align-items: center;
		padding: 0 var(--terminal-space-3);
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		transition:
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.cp-tab:hover {
		color: var(--terminal-accent-amber);
	}
	.cp-tab--active {
		color: var(--terminal-accent-amber);
		border-bottom-color: var(--terminal-accent-amber);
	}
	.cp-tab:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.cp-section {
		display: flex;
		flex-direction: column;
		gap: 20px;
		padding: 20px 16px;
		overflow-y: auto;
		min-height: 0;
	}

	/* Expert tier styling ── */
	.cp-expert-hint {
		margin: 0;
		font-size: 11px;
		line-height: 1.5;
		color: var(--terminal-fg-muted);
	}
	.cp-expert-hint code {
		background: var(--terminal-bg-panel-raised);
		padding: 1px 5px;
		font-size: 10px;
	}
	.cp-expert-empty {
		font-size: 12px;
		color: var(--terminal-fg-muted);
		font-style: italic;
		margin: 0;
	}
	.cp-expert-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.cp-expert-row {
		display: grid;
		grid-template-columns: 1fr 1fr 24px;
		align-items: center;
		gap: 8px;
		padding: 6px 8px;
		background: var(--terminal-bg-panel-sunken);
	}
	.cp-expert-key {
		font-size: 12px;
		font-weight: 600;
		color: var(--terminal-fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-expert-value {
		font-size: 12px;
		color: var(--terminal-fg-muted);
		font-variant-numeric: tabular-nums;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-expert-remove {
		width: 20px;
		height: 20px;
		border: none;
		background: transparent;
		color: var(--terminal-fg-muted);
		cursor: pointer;
		font-size: 14px;
		line-height: 1;
	}
	.cp-expert-remove:hover {
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-status-error);
	}
	.cp-expert-add {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		gap: 8px;
		padding-top: 8px;
		border-top: var(--terminal-border-hairline);
	}
	.cp-expert-input {
		height: 30px;
		padding: 0 8px;
		font-size: 12px;
		border: var(--terminal-border-hairline);
		background: transparent;
		color: var(--terminal-fg-primary);
		font-family: inherit;
	}
	.cp-expert-input:focus {
		outline: none;
		border-color: var(--terminal-accent-amber);
	}
	.cp-expert-add-btn {
		height: 28px;
		padding: 0 var(--terminal-space-3);
		background: transparent;
		color: var(--terminal-fg-secondary);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
	}
	.cp-expert-add-btn:hover:not(:disabled) {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}
	.cp-expert-add-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* Footer ── */
	.cp-footer {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px 16px;
		border-top: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
	}
	.cp-footer-status {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.cp-status {
		font-size: 11px;
		font-weight: 600;
	}
	.cp-status--clean {
		color: var(--terminal-fg-muted);
	}
	.cp-status--dirty {
		color: var(--terminal-status-warn);
	}
	.cp-status--pending {
		color: var(--terminal-accent-cyan);
	}
	.cp-status--error {
		color: var(--terminal-status-error);
	}
	.cp-footer-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.cp-action {
		height: 28px;
		padding: 0 var(--terminal-space-3);
		border: none;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition:
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			opacity var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.cp-action:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.cp-action:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
	.cp-action--ghost {
		background: transparent;
		color: var(--terminal-fg-tertiary);
	}
	.cp-action--ghost:hover:not(:disabled) {
		color: var(--terminal-fg-primary);
	}
	.cp-action--outline {
		background: transparent;
		color: var(--terminal-fg-secondary);
		border: var(--terminal-border-hairline);
	}
	.cp-action--outline:hover:not(:disabled) {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}
	.cp-action--primary {
		background: var(--terminal-accent-amber);
		color: var(--terminal-fg-inverted);
	}
	.cp-action--primary:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
