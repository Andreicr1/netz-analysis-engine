<!--
  Investment Policy — reactive config editor with sliders.
  Four sections: Risk Limits, Scoring Weights, Universe Filters, Rebalancing Rules.
  Risk Limits and Scoring save via PUT /admin/configs/defaults/liquid_funds/{config_type}.
  Universe Filters and Rebalancing are session-only (no backend config_type yet).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { SectionCard } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Switch } from "@investintell/ui/components/ui/switch";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import {
		ShieldCheck, FloppyDisk, Check, Warning,
	} from "phosphor-svelte";

	let { data }: { data: PageData } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// ── Helpers ──
	function findConfig(type: string): Record<string, any> | undefined {
		return data.configs.find((c: any) => c.config_type === type)?.value;
	}
	function getCalibration(): Record<string, any> {
		return findConfig("calibration") ?? {};
	}
	function getScoringConfig(): Record<string, any> {
		return findConfig("scoring") ?? {};
	}

	// ── Toast state ──
	let toast = $state<{ message: string; type: "success" | "error" } | null>(null);
	function showToast(message: string, type: "success" | "error" = "success") {
		toast = { message, type };
		setTimeout(() => { toast = null; }, 3000);
	}

	// ── Section: Risk Limits ──
	const defaultRiskLimits = {
		conservative: { cvar_limit: 5.0, var_limit: 4.0, max_drawdown: 15, min_liquidity: 80 },
		balanced:     { cvar_limit: 8.0, var_limit: 6.0, max_drawdown: 25, min_liquidity: 60 },
		aggressive:   { cvar_limit: 12.0, var_limit: 10.0, max_drawdown: 35, min_liquidity: 40 },
	};
	// Read from calibration.cvar_limits — map to UI shape
	const calibration = getCalibration();
	const cvarLimits = calibration.cvar_limits ?? {};
	const savedRiskLimits = Object.keys(cvarLimits).length > 0 ? {
		conservative: {
			cvar_limit:    Math.abs((cvarLimits.conservative?.cvar_95_lm ?? -0.05) * 100),
			var_limit:     Math.abs((cvarLimits.conservative?.cvar_95_lm ?? -0.05) * 100 * 0.8),
			max_drawdown:  Math.abs((cvarLimits.conservative?.cvar_95_lm ?? -0.05) * 100 * 3),
			min_liquidity: 80,
		},
		balanced: {
			cvar_limit:    Math.abs((cvarLimits.moderate?.cvar_95_lm ?? -0.08) * 100),
			var_limit:     Math.abs((cvarLimits.moderate?.cvar_95_lm ?? -0.08) * 100 * 0.75),
			max_drawdown:  Math.abs((cvarLimits.moderate?.cvar_95_lm ?? -0.08) * 100 * 3),
			min_liquidity: 60,
		},
		aggressive: {
			cvar_limit:    Math.abs((cvarLimits.growth?.cvar_95_lm ?? -0.15) * 100),
			var_limit:     Math.abs((cvarLimits.growth?.cvar_95_lm ?? -0.15) * 100 * 0.67),
			max_drawdown:  Math.abs((cvarLimits.growth?.cvar_95_lm ?? -0.15) * 100 * 2.3),
			min_liquidity: 40,
		},
	} : null;
	let riskLimits = $state(structuredClone(savedRiskLimits ?? defaultRiskLimits));
	let riskLimitsSnapshot = JSON.stringify(riskLimits);
	let riskLimitsDirty = $derived(JSON.stringify(riskLimits) !== riskLimitsSnapshot);
	let riskLimitsSaving = $state(false);

	const riskProfiles = [
		{ key: "conservative", label: "Conservative Income" },
		{ key: "balanced", label: "Balanced Growth" },
		{ key: "aggressive", label: "Aggressive Growth" },
	] as const;

	const riskFields = [
		{ key: "cvar_limit", label: "CVaR Limit", min: 0, max: 25, step: 0.5, unit: "%" },
		{ key: "var_limit", label: "VaR Limit", min: 0, max: 20, step: 0.5, unit: "%" },
		{ key: "max_drawdown", label: "Max Drawdown", min: 0, max: 50, step: 1, unit: "%" },
		{ key: "min_liquidity", label: "Min Liquidity", min: 0, max: 100, step: 5, unit: "%" },
	] as const;

	// ── Section: Scoring Weights ──
	const defaultScoringWeights = {
		return_consistency: 20, risk_adjusted_return: 25, drawdown_control: 20,
		information_ratio: 15, flows_momentum: 10, fee_efficiency: 10,
	};
	// Read from scoring.fund.weights
	const scoringRaw = getScoringConfig();
	const scoringFundWeights = scoringRaw?.fund?.weights ?? {};
	const savedScoring = Object.keys(scoringFundWeights).length > 0 ? {
		return_consistency:   Math.round((scoringFundWeights.pct_positive_months         ?? 0.2) * 100),
		risk_adjusted_return: Math.round((scoringFundWeights.sharpe_ratio                ?? 0.25) * 100),
		drawdown_control:     Math.round((scoringFundWeights.max_drawdown                ?? 0.2) * 100),
		information_ratio:    Math.round((scoringFundWeights.correlation_diversification  ?? 0.15) * 100),
		flows_momentum:       Math.round((scoringFundWeights.flows_momentum              ?? 0.1) * 100),
		fee_efficiency:       Math.round((scoringFundWeights.fee_efficiency               ?? 0.1) * 100),
	} : null;
	let scoringWeights = $state(structuredClone(savedScoring ?? defaultScoringWeights));
	let scoringSnapshot = JSON.stringify(scoringWeights);
	let scoringDirty = $derived(JSON.stringify(scoringWeights) !== scoringSnapshot);
	let scoringSaving = $state(false);
	let autoNormalize = $state(false);

	const scoringComponents = [
		{ key: "return_consistency", label: "Return Consistency" },
		{ key: "risk_adjusted_return", label: "Risk-Adjusted Return" },
		{ key: "drawdown_control", label: "Drawdown Control" },
		{ key: "information_ratio", label: "Information Ratio" },
		{ key: "flows_momentum", label: "Flows Momentum" },
		{ key: "fee_efficiency", label: "Fee Efficiency" },
	] as const;

	let scoringTotal = $derived(
		Object.values(scoringWeights).reduce((sum: number, v: any) => sum + (Number(v) || 0), 0)
	);

	function normalizeWeights() {
		const total = scoringTotal;
		if (total === 0) return;
		for (const comp of scoringComponents) {
			scoringWeights[comp.key] = Math.round((scoringWeights[comp.key] / total) * 100);
		}
		// Adjust rounding error on last component
		const newTotal = Object.values(scoringWeights).reduce((s: number, v: any) => s + (Number(v) || 0), 0);
		if (newTotal !== 100) {
			const lastKey = scoringComponents[scoringComponents.length - 1]?.key;
			if (lastKey) scoringWeights[lastKey] += 100 - newTotal;
		}
	}

	// ── Section: Universe Filters ──
	const defaultFilters = {
		min_aum_m: 100, max_expense_ratio: 1.5, exclude_index_funds: false,
		exclude_target_date: false, min_track_record_years: 3,
	};
	const savedFilters = findConfig("universe_filters");
	let universeFilters = $state(structuredClone(savedFilters ?? defaultFilters));
	let filtersSnapshot = JSON.stringify(universeFilters);
	let filtersDirty = $derived(JSON.stringify(universeFilters) !== filtersSnapshot);
	let filtersSaving = $state(false);

	// ── Section: Rebalancing Rules ──
	const defaultRebalancing = {
		drift_threshold: 5, frequency: "monthly", min_trade_size: 10000,
	};
	const savedRebalancing = findConfig("rebalancing");
	let rebalancingRules = $state(structuredClone(savedRebalancing ?? defaultRebalancing));
	let rebalancingSnapshot = JSON.stringify(rebalancingRules);
	let rebalancingDirty = $derived(JSON.stringify(rebalancingRules) !== rebalancingSnapshot);
	let rebalancingSaving = $state(false);

	// ── Active section for left nav ──
	let activeSection = $state("risk-limits");

	function scrollTo(id: string) {
		activeSection = id;
		document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
	}

	// ── Save handlers ──
	async function saveRiskLimits() {
		riskLimitsSaving = true;
		try {
			// Convert UI shape back to calibration.cvar_limits format
			const calibrationPatch = structuredClone(getCalibration());
			calibrationPatch.cvar_limits = {
				conservative: {
					cvar_95_lm: -(riskLimits.conservative.cvar_limit / 100),
					warning_threshold: 0.8,
					breach_consecutive_days: 5,
				},
				moderate: {
					cvar_95_lm: -(riskLimits.balanced.cvar_limit / 100),
					warning_threshold: 0.8,
					breach_consecutive_days: 3,
				},
				growth: {
					cvar_95_lm: -(riskLimits.aggressive.cvar_limit / 100),
					warning_threshold: 0.8,
					breach_consecutive_days: 5,
				},
			};
			await api.put("/admin/configs/defaults/liquid_funds/calibration", calibrationPatch);
			riskLimitsSnapshot = JSON.stringify(riskLimits);
			showToast("Risk limits saved");
		} catch {
			showToast("Failed to save risk limits", "error");
		} finally {
			riskLimitsSaving = false;
		}
	}

	async function saveScoringWeights() {
		scoringSaving = true;
		try {
			// Convert UI percentages back to scoring.fund.weights decimals
			const scoringPatch = structuredClone(getScoringConfig());
			if (!scoringPatch.fund) scoringPatch.fund = {};
			scoringPatch.fund.weights = {
				pct_positive_months:         scoringWeights.return_consistency   / 100,
				sharpe_ratio:                scoringWeights.risk_adjusted_return / 100,
				max_drawdown:                scoringWeights.drawdown_control     / 100,
				correlation_diversification: scoringWeights.information_ratio    / 100,
				flows_momentum:              scoringWeights.flows_momentum       / 100,
				fee_efficiency:              scoringWeights.fee_efficiency        / 100,
			};
			await api.put("/admin/configs/defaults/liquid_funds/scoring", scoringPatch);
			scoringSnapshot = JSON.stringify(scoringWeights);
			showToast("Scoring weights saved");
		} catch {
			showToast("Failed to save scoring weights", "error");
		} finally {
			scoringSaving = false;
		}
	}

	async function saveUniverseFilters() {
		// universe_filters has no dedicated config_type in backend yet.
		// Applied locally in session only.
		filtersSaving = true;
		try {
			filtersSnapshot = JSON.stringify(universeFilters);
			showToast("Universe filters applied (session only)");
		} catch {
			showToast("Failed to save universe filters", "error");
		} finally {
			filtersSaving = false;
		}
	}

	async function saveRebalancingRules() {
		// rebalancing has no dedicated config_type in backend yet.
		// drift_bands live in calibration.drift_bands — TODO: persist there.
		rebalancingSaving = true;
		rebalancingSnapshot = JSON.stringify(rebalancingRules);
		showToast("Rebalancing rules applied (session only)");
		rebalancingSaving = false;
	}
</script>

<div class="ip-page">
	<!-- Left nav -->
	<aside class="ip-nav">
		<div class="ip-nav-header">
			<ShieldCheck size={18} weight="light" />
			<span>Investment Policy</span>
		</div>
		<nav class="ip-nav-links">
			<button class="ip-nav-link" class:active={activeSection === "risk-limits"} onclick={() => scrollTo("risk-limits")} type="button">
				Risk Limits
			</button>
			<button class="ip-nav-link" class:active={activeSection === "scoring-weights"} onclick={() => scrollTo("scoring-weights")} type="button">
				Scoring Weights
			</button>
			<button class="ip-nav-link" class:active={activeSection === "universe-filters"} onclick={() => scrollTo("universe-filters")} type="button">
				Universe Filters
			</button>
			<button class="ip-nav-link" class:active={activeSection === "rebalancing-rules"} onclick={() => scrollTo("rebalancing-rules")} type="button">
				Rebalancing Rules
			</button>
		</nav>
	</aside>

	<!-- Main content -->
	<div class="ip-content">

		<!-- ── Risk Limits ── -->
		<section id="risk-limits" class="ip-section">
			<SectionCard title="Risk Limits">
				<div class="ip-cards">
					{#each riskProfiles as profile (profile.key)}
						<div class="ip-card">
							<h4 class="ip-card-title">{profile.label}</h4>
							{#each riskFields as field (field.key)}
								<div class="ip-slider-row">
									<label class="ip-slider-label">{field.label}</label>
									<div class="ip-slider-control">
										<input
											type="range"
											class="ip-range"
											min={field.min}
											max={field.max}
											step={field.step}
											bind:value={riskLimits[profile.key][field.key]}
										/>
										<span class="ip-slider-value">{riskLimits[profile.key][field.key]}{field.unit}</span>
									</div>
								</div>
							{/each}
						</div>
					{/each}
				</div>
				<div class="ip-section-footer">
					<Button
						variant="default"
						size="sm"
						disabled={!riskLimitsDirty || riskLimitsSaving}
						onclick={saveRiskLimits}
					>
						<FloppyDisk size={14} weight="light" class="mr-1.5" />
						{riskLimitsSaving ? "Saving…" : "Save"}
					</Button>
				</div>
			</SectionCard>
		</section>

		<!-- ── Scoring Weights ── -->
		<section id="scoring-weights" class="ip-section">
			<SectionCard title="Scoring Weights">
				<div class="ip-scoring-grid">
					{#each scoringComponents as comp (comp.key)}
						<div class="ip-scoring-row">
							<label class="ip-scoring-label">{comp.label}</label>
							<div class="ip-scoring-input-wrapper">
								<input
									type="number"
									class="ip-scoring-input"
									min={0}
									max={100}
									step={1}
									bind:value={scoringWeights[comp.key]}
								/>
								<span class="ip-scoring-unit">%</span>
							</div>
							<div class="ip-scoring-bar-track">
								<div
									class="ip-scoring-bar-fill"
									style:width="{Math.min(100, Math.max(0, scoringWeights[comp.key] || 0))}%"
								></div>
							</div>
						</div>
					{/each}
				</div>

				<div class="ip-scoring-total" class:error={Math.round(scoringTotal) !== 100}>
					{#if Math.round(scoringTotal) === 100}
						<Check size={14} weight="light" />
					{:else}
						<Warning size={14} weight="light" />
					{/if}
					<span>Total: {scoringTotal}%</span>
				</div>

				<div class="ip-scoring-actions">
					<label class="ip-toggle-row">
						<Switch bind:checked={autoNormalize} onCheckedChange={(v) => { if (v) normalizeWeights(); }} />
						<span class="ip-toggle-label">Auto-normalize</span>
					</label>
					<Button
						variant="default"
						size="sm"
						disabled={!scoringDirty || scoringSaving}
						onclick={saveScoringWeights}
					>
						<FloppyDisk size={14} weight="light" class="mr-1.5" />
						{scoringSaving ? "Saving…" : "Save Weights"}
					</Button>
				</div>
			</SectionCard>
		</section>

		<!-- ── Universe Filters ── -->
		<section id="universe-filters" class="ip-section">
			<SectionCard title="Universe Filters">
				<div class="ip-filters-grid">
					<div class="ip-filter-row">
						<label class="ip-filter-label">Min AUM</label>
						<div class="ip-filter-input-group">
							<span class="ip-filter-prefix">$</span>
							<input
								type="number"
								class="ip-filter-input"
								min={0}
								step={10}
								bind:value={universeFilters.min_aum_m}
							/>
							<span class="ip-filter-suffix">M</span>
						</div>
					</div>

					<div class="ip-filter-row">
						<label class="ip-filter-label">Max Expense Ratio</label>
						<div class="ip-slider-control">
							<input
								type="range"
								class="ip-range"
								min={0}
								max={3}
								step={0.05}
								bind:value={universeFilters.max_expense_ratio}
							/>
							<span class="ip-slider-value">{universeFilters.max_expense_ratio}%</span>
						</div>
					</div>

					<div class="ip-filter-row">
						<label class="ip-filter-label">Exclude Index Funds</label>
						<Switch bind:checked={universeFilters.exclude_index_funds} />
					</div>

					<div class="ip-filter-row">
						<label class="ip-filter-label">Exclude Target Date</label>
						<Switch bind:checked={universeFilters.exclude_target_date} />
					</div>

					<div class="ip-filter-row">
						<label class="ip-filter-label">Min Track Record</label>
						<div class="ip-filter-input-group">
							<input
								type="number"
								class="ip-filter-input"
								min={0}
								max={30}
								step={1}
								bind:value={universeFilters.min_track_record_years}
							/>
							<span class="ip-filter-suffix">years</span>
						</div>
					</div>
				</div>

				<div class="ip-section-footer">
					<Button
						variant="default"
						size="sm"
						disabled={!filtersDirty || filtersSaving}
						onclick={saveUniverseFilters}
					>
						<FloppyDisk size={14} weight="light" class="mr-1.5" />
						{filtersSaving ? "Saving…" : "Save Filters"}
					</Button>
				</div>
			</SectionCard>
		</section>

		<!-- ── Rebalancing Rules ── -->
		<section id="rebalancing-rules" class="ip-section">
			<SectionCard title="Rebalancing Rules">
				<div class="ip-filters-grid">
					<div class="ip-filter-row">
						<label class="ip-filter-label">Drift Threshold</label>
						<div class="ip-slider-control">
							<input
								type="range"
								class="ip-range"
								min={1}
								max={15}
								step={0.5}
								bind:value={rebalancingRules.drift_threshold}
							/>
							<span class="ip-slider-value">{rebalancingRules.drift_threshold}%</span>
						</div>
					</div>

					<div class="ip-filter-row">
						<label class="ip-filter-label">Frequency</label>
						<select class="ip-select" bind:value={rebalancingRules.frequency}>
							<option value="weekly">Weekly</option>
							<option value="monthly">Monthly</option>
							<option value="quarterly">Quarterly</option>
						</select>
					</div>

					<div class="ip-filter-row">
						<label class="ip-filter-label">Min Trade Size</label>
						<div class="ip-filter-input-group">
							<span class="ip-filter-prefix">$</span>
							<input
								type="number"
								class="ip-filter-input"
								min={0}
								step={1000}
								bind:value={rebalancingRules.min_trade_size}
							/>
						</div>
					</div>
				</div>

				<div class="ip-section-footer">
					<Button
						variant="default"
						size="sm"
						disabled={!rebalancingDirty || rebalancingSaving}
						onclick={saveRebalancingRules}
					>
						<FloppyDisk size={14} weight="light" class="mr-1.5" />
						{rebalancingSaving ? "Saving…" : "Save Rules"}
					</Button>
				</div>
			</SectionCard>
		</section>
	</div>
</div>

<!-- Toast notification -->
{#if toast}
	<div class="ip-toast" class:error={toast.type === "error"}>
		{#if toast.type === "success"}
			<Check size={14} weight="light" />
		{:else}
			<Warning size={14} weight="light" />
		{/if}
		{toast.message}
	</div>
{/if}

<style>
	/* ── Page layout — two columns ── */
	.ip-page {
		display: flex;
		gap: 0;
		min-height: 100%;
		padding: 32px 0;
	}

	/* ── Left nav ── */
	.ip-nav {
		position: sticky;
		top: 32px;
		width: 260px;
		min-width: 260px;
		padding-right: 32px;
		align-self: flex-start;
	}

	.ip-nav-header {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 15px;
		font-weight: 700;
		color: var(--ii-text-primary);
		padding-bottom: 16px;
		border-bottom: 1px solid var(--ii-border-subtle);
		margin-bottom: 12px;
	}

	.ip-nav-links {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ip-nav-link {
		display: block;
		padding: 8px 12px;
		border: none;
		background: transparent;
		text-align: left;
		border-radius: var(--ii-radius-md, 6px);
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary);
		cursor: pointer;
		transition: color 120ms ease, background 120ms ease;
	}

	.ip-nav-link:hover {
		color: var(--ii-text-primary);
		background: var(--ii-surface-alt);
	}

	.ip-nav-link.active {
		color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
		font-weight: 600;
	}

	/* ── Main content ── */
	.ip-content {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 32px;
	}

	.ip-section {
		scroll-margin-top: 32px;
	}

	/* ── Risk limit cards ── */
	.ip-cards {
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.ip-card {
		padding: 20px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-lg, 8px);
		background: var(--ii-surface);
	}

	.ip-card-title {
		font-size: 14px;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 16px;
	}

	/* ── Slider rows ── */
	.ip-slider-row {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 8px 0;
	}

	.ip-slider-label {
		width: 140px;
		min-width: 140px;
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary);
	}

	.ip-slider-control {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.ip-range {
		flex: 1;
		height: 4px;
		appearance: none;
		background: var(--ii-border);
		border-radius: 2px;
		outline: none;
		cursor: pointer;
	}

	.ip-range::-webkit-slider-thumb {
		appearance: none;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--ii-brand-primary);
		border: 2px solid var(--ii-surface);
		box-shadow: 0 0 0 1px var(--ii-brand-primary);
		cursor: pointer;
	}

	.ip-range::-moz-range-thumb {
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--ii-brand-primary);
		border: 2px solid var(--ii-surface);
		box-shadow: 0 0 0 1px var(--ii-brand-primary);
		cursor: pointer;
	}

	.ip-slider-value {
		min-width: 48px;
		text-align: right;
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-mono);
		color: var(--ii-text-primary);
	}

	/* ── Scoring weights ── */
	.ip-scoring-grid {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.ip-scoring-row {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.ip-scoring-label {
		width: 180px;
		min-width: 180px;
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary);
	}

	.ip-scoring-input-wrapper {
		display: flex;
		align-items: center;
		gap: 4px;
		min-width: 80px;
	}

	.ip-scoring-input {
		width: 56px;
		height: 32px;
		padding: 0 8px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: 13px;
		font-family: var(--ii-font-mono);
		text-align: right;
		outline: none;
	}

	.ip-scoring-input:focus {
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	.ip-scoring-unit {
		font-size: 12px;
		color: var(--ii-text-muted);
	}

	.ip-scoring-bar-track {
		flex: 1;
		height: 6px;
		background: var(--ii-border-subtle);
		border-radius: 3px;
		overflow: hidden;
	}

	.ip-scoring-bar-fill {
		height: 100%;
		background: var(--ii-brand-primary);
		border-radius: 3px;
		transition: width 150ms ease;
	}

	.ip-scoring-total {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 16px;
		padding: 10px 14px;
		border-radius: var(--ii-radius-md, 6px);
		background: color-mix(in srgb, var(--ii-success) 8%, transparent);
		color: var(--ii-success);
		font-size: 13px;
		font-weight: 600;
	}

	.ip-scoring-total.error {
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
	}

	.ip-scoring-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-top: 16px;
	}

	.ip-toggle-row {
		display: flex;
		align-items: center;
		gap: 8px;
		cursor: pointer;
	}

	.ip-toggle-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary);
	}

	/* ── Filters grid ── */
	.ip-filters-grid {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.ip-filter-row {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.ip-filter-label {
		width: 180px;
		min-width: 180px;
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary);
	}

	.ip-filter-input-group {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.ip-filter-prefix, .ip-filter-suffix {
		font-size: 13px;
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.ip-filter-input {
		width: 100px;
		height: 32px;
		padding: 0 8px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: 13px;
		font-family: var(--ii-font-mono);
		outline: none;
	}

	.ip-filter-input:focus {
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	.ip-select {
		height: 32px;
		padding: 0 32px 0 10px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: 13px;
		outline: none;
		cursor: pointer;
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%236B7280' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 10px center;
	}

	.ip-select:focus {
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	/* ── Section footer ── */
	.ip-section-footer {
		display: flex;
		justify-content: flex-end;
		margin-top: 20px;
		padding-top: 16px;
		border-top: 1px solid var(--ii-border-subtle);
	}

	/* ── Toast ── */
	.ip-toast {
		position: fixed;
		bottom: 24px;
		right: 24px;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 18px;
		border-radius: var(--ii-radius-md, 6px);
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-success);
		color: var(--ii-success);
		font-size: 13px;
		font-weight: 600;
		box-shadow: 0 4px 12px rgba(0,0,0,0.12);
		z-index: 1000;
		animation: ip-toast-in 200ms ease-out;
	}

	.ip-toast.error {
		border-color: var(--ii-danger);
		color: var(--ii-danger);
	}

	@keyframes ip-toast-in {
		from { opacity: 0; transform: translateY(8px); }
		to { opacity: 1; transform: translateY(0); }
	}

	/* ── Responsive ── */
	@media (max-width: 767px) {
		.ip-page { flex-direction: column; }
		.ip-nav { position: static; width: 100%; min-width: 0; padding-right: 0; padding-bottom: 16px; }
		.ip-nav-links { flex-direction: row; overflow-x: auto; gap: 4px; }
		.ip-slider-row { flex-direction: column; align-items: flex-start; gap: 6px; }
		.ip-slider-label { width: auto; min-width: 0; }
		.ip-scoring-row { flex-direction: column; align-items: flex-start; gap: 6px; }
		.ip-scoring-label { width: auto; min-width: 0; }
		.ip-filter-row { flex-direction: column; align-items: flex-start; gap: 6px; }
		.ip-filter-label { width: auto; min-width: 0; }
	}
</style>
