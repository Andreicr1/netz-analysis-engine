<!--
  ConstructionNarrative — first-class narrative surface for the last
  construction run. Phase 4 Task 4.3 of the portfolio-enterprise-workbench
  plan.

  Layout: 2-column grid.
    - Left  → Jinja2 templater output (headline, key points,
              constraint story, holding changes, advisor recommendations
              when ``advisor_enabled``).
    - Right → Sticky NarrativeMetricsStrip showing the 4 ex-ante metrics
              with ``ex_ante_vs_previous`` delta badges.

  Consumes ``workspace.constructionRun`` (ConstructionRunPayload from
  GET /model-portfolios/{id}/runs/{run_id}). Empty states are strict
  per OD-26 — the panel NEVER renders mock values.

  Per CLAUDE.md Stability Guardrails charter §3 — detail surfaces use
  ``<svelte:boundary>`` + ``PanelErrorState`` failed snippet.
-->
<script lang="ts">
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";
	import {
		EmptyState,
		formatDateTime,
		formatNumber,
	} from "@investintell/ui";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import NarrativeHeadline from "./NarrativeHeadline.svelte";
	import NarrativeMetricsStrip from "./NarrativeMetricsStrip.svelte";
	import HoldingChangesList from "./HoldingChangesList.svelte";

	const run = $derived(workspace.constructionRun);
	const phase = $derived(workspace.runPhase);
	const error = $derived(workspace.runError);

	const narrative = $derived(run?.narrative ?? null);

	const advisorEnabled = $derived.by(() => {
		// Advisor section renders only when the calibration has it on
		// AND the run actually carries an advisor payload (DL6 — advisor
		// is skipped when the optimizer phase 1 failed).
		const cal = workspace.calibration;
		return Boolean(cal?.advisor_enabled && run?.advisor);
	});

	const holdingChanges = $derived(narrative?.holding_changes ?? []);
	const phaseLabel = $derived.by(() => {
		switch (phase) {
			case "running":
				return "Starting construction run…";
			case "optimizer":
				return "Optimizing portfolio allocation…";
			case "stress":
				return "Running stress scenarios…";
			case "done":
				return "Done";
			case "error":
				return "Run failed";
			default:
				return "Idle";
		}
	});

	function formatAdvisorField(key: string, value: unknown): string {
		if (value === null || value === undefined) return "—";
		if (typeof value === "number") {
			if (key.includes("pct") || key.includes("gap") || key.includes("cvar")) {
				return `${formatNumber(value * 100, 2)}%`;
			}
			return formatNumber(value, 4);
		}
		if (typeof value === "boolean") return value ? "yes" : "no";
		if (typeof value === "string") return value;
		return JSON.stringify(value);
	}

	const advisorEntries = $derived.by(() => {
		if (!run?.advisor || typeof run.advisor !== "object") return [];
		return Object.entries(run.advisor as Record<string, unknown>).filter(
			([, v]) => v !== null && v !== undefined && typeof v !== "object",
		);
	});
</script>

<svelte:boundary>
	<div class="cn-root">
		{#if phase === "running" || phase === "optimizer" || phase === "stress"}
			<!-- Running — institutional progress state -->
			<div class="cn-empty">
				<EmptyState
					title={phaseLabel}
					message="The construction run is in progress. The narrative will appear when the optimizer, stress suite, validation, and templater finish."
				/>
			</div>
		{:else if phase === "error"}
			<!-- Failed — show the error reason, no mock fallback (OD-26) -->
			<div class="cn-empty">
				<EmptyState
					title="Last run failed"
					message={error ?? "The construction job reported an error without a reason."}
				/>
			</div>
		{:else if !run}
			<!-- No run yet — strict empty state -->
			<div class="cn-empty">
				<EmptyState
					title="No construction run yet"
					message="Press Run Construct in the Builder to generate a portfolio and its narrative."
				/>
			</div>
		{:else if !narrative}
			<!-- Run present but narrative missing — backend contract violation -->
			<div class="cn-empty">
				<EmptyState
					title="Narrative missing"
					message="The last run succeeded but no narrative block was returned. The templater may be stale."
				/>
			</div>
		{:else}
			<div class="cn-grid">
				<!-- ── Left column — narrative prose ───────────────── -->
				<section class="cn-main">
					<header class="cn-meta">
						<div class="cn-meta-row">
							<span class="cn-kicker">Construction run</span>
							{#if run.completed_at}
								<span class="cn-meta-time">
									Completed {formatDateTime(run.completed_at)}
								</span>
							{/if}
						</div>
						{#if run.wall_clock_ms !== null}
							<span class="cn-meta-timing">
								{formatNumber(run.wall_clock_ms / 1000, 1)}s wall clock
							</span>
						{/if}
					</header>

					<NarrativeHeadline
						headline={narrative.headline}
						keyPoints={narrative.key_points}
						constraintStory={narrative.constraint_story}
					/>

					{#if holdingChanges.length > 0}
						<HoldingChangesList changes={holdingChanges} />
					{/if}

					{#if advisorEnabled && advisorEntries.length > 0}
						<section class="cn-advisor">
							<header class="cn-section-head">
								<span class="cn-kicker">Advisor</span>
								<span class="cn-section-title">Construction recommendations</span>
							</header>
							<dl class="cn-advisor-list">
								{#each advisorEntries as [key, value] (key)}
									<div class="cn-advisor-row">
										<dt class="cn-advisor-key">{key.replace(/_/g, " ")}</dt>
										<dd class="cn-advisor-value">{formatAdvisorField(key, value)}</dd>
									</div>
								{/each}
							</dl>
						</section>
					{/if}
				</section>

				<!-- ── Right column — sticky metrics ───────────────── -->
				<NarrativeMetricsStrip
					metrics={run.ex_ante_metrics}
					deltas={run.ex_ante_vs_previous}
				/>
			</div>
		{/if}
	</div>

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Narrative failed to render"
			message={err instanceof Error ? err.message : "Unexpected error in the construction narrative."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.cn-root {
		height: 100%;
		min-height: 0;
		overflow: auto;
		background: #141519;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.cn-empty {
		padding: 32px 24px;
	}
	.cn-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 260px;
		gap: 20px;
		padding: 20px 24px;
	}
	@container (max-width: 720px) {
		.cn-grid {
			grid-template-columns: 1fr;
		}
	}

	.cn-main {
		display: flex;
		flex-direction: column;
		gap: 24px;
		min-width: 0;
	}

	.cn-meta {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
		padding-bottom: 12px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.cn-meta-row {
		display: flex;
		align-items: baseline;
		gap: 10px;
	}
	.cn-kicker {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.cn-meta-time {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
	}
	.cn-meta-timing {
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-muted, #85a0bd);
	}

	/* Advisor section ── */
	.cn-advisor {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 14px 16px;
		background: rgba(1, 119, 251, 0.04);
		border: 1px solid rgba(1, 119, 251, 0.24);
		border-radius: 8px;
	}
	.cn-section-head {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.cn-section-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.cn-advisor-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px 24px;
		margin: 0;
	}
	.cn-advisor-row {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.cn-advisor-key {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--ii-text-muted, #85a0bd);
		text-transform: capitalize;
	}
	.cn-advisor-value {
		margin: 0;
		font-size: 13px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
