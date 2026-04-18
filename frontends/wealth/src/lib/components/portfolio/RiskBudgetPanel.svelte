<!--
  RiskBudgetPanel — Builder risk budget surface. Composes:
    1. RiskBudgetSlider (operator edits the tail loss limit)
    2. AchievableReturnBandChart (derived from live preview ?? latest
       cascade_telemetry)
    3. Signal banner (operator_signal → copy + tone)

  PR-A13 shipped the static form; PR-A13.2 wires the live drag preview
  via POST /preview-cvar. ``previewBand ?? serverBand`` precedence lets
  the drag-derived band override the last completed run's band, while
  clearing ``previewBand`` on ``runPhase === "done"`` re-grants authority
  to the fresh server band (closes the two-channel state gap from
  PR-A13 Section B.2).
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PortfolioCalibration } from "$lib/types/portfolio-calibration";
	import type {
		AchievableReturnBand,
		OperatorMessage,
		OperatorSignal,
		WinnerSignal,
	} from "$lib/types/cascade-telemetry";
	import { defaultCvarForProfile } from "$lib/util/profile-defaults";
	import RiskBudgetSlider from "./RiskBudgetSlider.svelte";
	import AchievableReturnBandChart from "./AchievableReturnBandChart.svelte";

	interface Props {
		portfolio: ModelPortfolio;
		calibration: PortfolioCalibration;
		snapshot?: Partial<PortfolioCalibration> | null;
		onChange: (patch: Partial<PortfolioCalibration>) => void;
	}

	let { portfolio, calibration, snapshot, onChange }: Props = $props();

	const profileDefault = $derived(defaultCvarForProfile(portfolio.profile));
	const cvarLimit = $derived(calibration.cvar_limit);

	// ── Server-channel state (authoritative when no live preview) ──
	const serverBand = $derived(
		workspace.constructionRun?.cascade_telemetry?.achievable_return_band ?? null,
	);
	const serverSignal = $derived(
		workspace.constructionRun?.cascade_telemetry?.operator_signal ?? null,
	);
	const serverMinCvar = $derived(
		workspace.constructionRun?.cascade_telemetry?.min_achievable_cvar ?? null,
	);
	// PR-A19.1 Section C — cascade-aware signal + backend-owned copy.
	const winnerSignal = $derived<WinnerSignal | null>(
		workspace.constructionRun?.cascade_telemetry?.winner_signal ?? null,
	);
	const operatorMessage = $derived<OperatorMessage | null>(
		workspace.constructionRun?.cascade_telemetry?.operator_message ?? null,
	);

	// ── Preview-channel state (PR-A13.2 live drag) ─────────────────
	let previewBand = $state<AchievableReturnBand | null>(null);
	let previewSignal = $state<OperatorSignal | null>(null);
	let previewMinCvar = $state<number | null>(null);
	let previewing = $state(false);
	let previewError = $state<string | null>(null);

	const band = $derived(previewBand ?? serverBand);
	const signal = $derived(previewSignal ?? serverSignal);
	const minAchievableCvar = $derived(previewMinCvar ?? serverMinCvar);

	const belowFloor = $derived(signal?.kind === "cvar_limit_below_universe_floor");
	const dataMissing = $derived(signal?.kind === "upstream_data_missing");
	const polytopeEmpty = $derived(signal?.kind === "constraint_polytope_empty");

	// ── Debounced preview fetch ────────────────────────────────────
	// 250ms debounce on slider mutations. AbortController cancels stale
	// in-flight requests so rapid drags don't produce a late response that
	// overwrites a newer one.
	let previewTimer: ReturnType<typeof setTimeout> | null = null;
	let previewAbort: AbortController | null = null;
	let lastPreviewedCvar: number | null = null;

	$effect(() => {
		const cv = cvarLimit;
		// Skip when the operator hasn't moved from the current calibration
		// value — server band is already authoritative in that case.
		if (cv === null || cv === undefined) return;
		if (cv === lastPreviewedCvar) return;
		if (previewTimer) clearTimeout(previewTimer);
		previewTimer = setTimeout(() => {
			void runPreview(cv);
		}, 250);
		return () => {
			if (previewTimer) {
				clearTimeout(previewTimer);
				previewTimer = null;
			}
		};
	});

	// Clear the preview channel once a new construction completes so the
	// freshly-authoritative server band wins. Without this, a stale drag
	// preview would continue masking the real completed-run band.
	$effect(() => {
		if (workspace.runPhase === "done") {
			previewBand = null;
			previewSignal = null;
			previewMinCvar = null;
			previewError = null;
			lastPreviewedCvar = null;
		}
	});

	async function runPreview(cv: number): Promise<void> {
		previewAbort?.abort();
		const ac = new AbortController();
		previewAbort = ac;
		previewing = true;
		previewError = null;
		try {
			const res = await workspace.previewCvar(cv, ac.signal);
			if (ac.signal.aborted) return;
			if (res === null) return;
			previewBand = res.achievable_return_band;
			previewSignal = res.operator_signal;
			previewMinCvar = res.min_achievable_cvar;
			lastPreviewedCvar = cv;
		} catch (err) {
			if (ac.signal.aborted) return;
			if (err instanceof DOMException && err.name === "AbortError") return;
			// Preserve last good preview; surface a non-blocking chip.
			previewError =
				err instanceof Error ? err.message : "Live preview unavailable";
		} finally {
			if (previewAbort === ac) previewAbort = null;
			previewing = false;
		}
	}
</script>

<div class="rbp-root">
	<RiskBudgetSlider
		value={cvarLimit}
		{profileDefault}
		profile={portfolio.profile}
		onChange={(v) => onChange({ cvar_limit: v })}
		originalValue={snapshot?.cvar_limit as number | undefined}
	/>

	{#if dataMissing}
		<div class="rbp-banner rbp-banner--empty" role="status">
			<p class="rbp-banner__msg">
				We don't have enough return history for this universe to model an achievable
				range. Add instruments with at least 36 months of NAV, or check the Universe
				column.
			</p>
		</div>
	{:else if polytopeEmpty}
		<div class="rbp-banner rbp-banner--blocking" role="alert">
			<p class="rbp-banner__msg">
				The current strategic allocation has no feasible portfolio. Adjust block
				min/max bounds.
			</p>
		</div>
	{:else}
		<div class="rbp-chart-frame" class:rbp-chart-frame--previewing={previewing}>
			<AchievableReturnBandChart
				{band}
				{cvarLimit}
				{minAchievableCvar}
				height={220}
			/>
			{#if previewing}
				<div class="rbp-preview-pulse" aria-label="Updating preview" data-testid="rbp-preview-spinner"></div>
			{/if}
		</div>
		{#if previewError}
			<div class="rbp-banner rbp-banner--preview-error" role="status" data-testid="rbp-preview-error">
				<p class="rbp-banner__msg">
					Live preview unavailable — showing the last completed run's band. Adjust
					the slider or trigger a full build.
				</p>
			</div>
		{/if}
		<div class="rbp-stats" data-testid="rbp-stats">
			{#if band}
				<div class="rbp-stats__primary">
					At your tail loss limit: <strong>{formatPercent(band.upper, 2)}</strong> expected
				</div>
				<div class="rbp-stats__range">
					Achievable range across this universe:
					{formatPercent(band.lower, 2)} – {formatPercent(band.upper, 2)}
				</div>
			{:else}
				<div class="rbp-stats__empty">
					Run a construction to see the achievable return band.
				</div>
			{/if}
		</div>
		{#if belowFloor && minAchievableCvar !== null}
			<div class="rbp-banner rbp-banner--warning" role="status">
				<p class="rbp-banner__msg">
					Your tail loss limit ({formatPercent(cvarLimit, 2)}) sits below the lowest
					tail risk this universe can deliver ({formatPercent(minAchievableCvar, 2)}).
					We're showing the lowest-tail-risk portfolio achievable. Loosen the limit or
					expand the universe.
				</p>
			</div>
		{/if}
		<!--
		  PR-A19.1 Section C — cascade-aware operator message.

		  Backend owns the displayable copy; frontend renders verbatim
		  (smart backend / dumb frontend). Shown only when the cascade
		  winner signal is non-optimal and the backend returned a
		  formatted message.
		-->
		{#if winnerSignal && winnerSignal !== "optimal" && operatorMessage}
			<div
				class="rbp-banner rbp-banner--{operatorMessage.severity}"
				role={operatorMessage.severity === "error" ? "alert" : "status"}
				data-testid="rbp-operator-message"
				data-winner-signal={winnerSignal}
			>
				<p class="rbp-banner__title">{operatorMessage.title}</p>
				<p class="rbp-banner__msg">{operatorMessage.body}</p>
			</div>
		{/if}
	{/if}
</div>

<style>
	.rbp-root {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.rbp-stats {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-family: var(--terminal-font-mono);
	}
	.rbp-stats__primary {
		font-size: 12px;
		color: var(--terminal-fg-primary);
	}
	.rbp-stats__range {
		font-size: 11px;
		color: var(--terminal-fg-muted);
	}
	.rbp-stats__empty {
		font-size: 11px;
		color: var(--terminal-fg-muted);
		font-style: italic;
	}
	.rbp-banner {
		padding: 10px 12px;
		border-left: 3px solid var(--terminal-fg-muted);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}
	.rbp-banner--warning {
		border-left-color: var(--terminal-status-warning);
	}
	.rbp-banner--blocking {
		border-left-color: var(--terminal-status-error);
	}
	.rbp-banner--empty {
		border-left-color: var(--terminal-fg-muted);
	}
	.rbp-banner__msg {
		margin: 0;
		font-size: 11px;
		line-height: 1.45;
		color: var(--terminal-fg-secondary);
	}
	.rbp-banner--preview-error {
		border-left-color: var(--terminal-status-warning);
	}
	/* PR-A19.1 — operator_message severity variants */
	.rbp-banner--info {
		border-left-color: var(--terminal-status-info, var(--terminal-fg-muted));
	}
	.rbp-banner--error {
		border-left-color: var(--terminal-status-error);
	}
	.rbp-banner__title {
		margin: 0 0 4px 0;
		font-size: 11px;
		font-weight: 600;
		color: var(--terminal-fg-primary);
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.rbp-chart-frame {
		position: relative;
	}
	.rbp-chart-frame--previewing {
		opacity: 0.85;
	}
	.rbp-preview-pulse {
		position: absolute;
		top: 8px;
		right: 8px;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--terminal-status-info, var(--terminal-fg-muted));
		animation: rbp-preview-pulse 1.2s ease-in-out infinite;
		pointer-events: none;
	}
	@keyframes rbp-preview-pulse {
		0%, 100% { opacity: 0.3; transform: scale(0.85); }
		50%      { opacity: 1;   transform: scale(1);    }
	}
</style>
