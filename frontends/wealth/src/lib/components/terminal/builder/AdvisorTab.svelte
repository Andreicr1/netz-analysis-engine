<!--
  AdvisorTab — Zone E ADVISOR tab of the Builder results panel.

  Migrated from ConstructionNarrative.svelte, restyled for terminal.
  Renders: headline, key points, ex-ante metrics strip, holding changes,
  advisor notes. All text plain institutional — no markdown rendering.
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { formatNumber, formatPercent } from "@investintell/ui";

	const run = $derived(workspace.constructionRun);
	const narrative = $derived(run?.narrative ?? null);
	const metrics = $derived(run?.ex_ante_metrics ?? null);
	const deltas = $derived(run?.ex_ante_vs_previous ?? null);
	const advisor = $derived(run?.advisor ?? null);
	const holdingChanges = $derived(narrative?.holding_changes ?? []);

	/** Sanitized metric labels for the stat slabs. */
	const METRIC_DISPLAY: Array<{
		key: string;
		label: string;
		format: (v: number) => string;
	}> = [
		{ key: "cvar_95", label: "Tail Loss (95%)", format: (v) => formatPercent(v, 2) },
		{ key: "expected_return", label: "Expected Return", format: (v) => formatPercent(v, 2) },
		{
			key: "portfolio_volatility",
			label: "Tracking Error",
			format: (v) => formatPercent(v, 2),
		},
		{ key: "sharpe_ratio", label: "Sharpe Ratio", format: (v) => formatNumber(v, 2) },
	];

	const advisorEntries = $derived.by(() => {
		if (!advisor || typeof advisor !== "object") return [];
		return Object.entries(advisor as Record<string, unknown>).filter(
			([, v]) => v !== null && v !== undefined && typeof v !== "object",
		);
	});

	function formatAdvisorValue(key: string, value: unknown): string {
		if (value === null || value === undefined) return "\u2014";
		if (typeof value === "number") {
			if (key.includes("pct") || key.includes("gap") || key.includes("cvar")) {
				return formatPercent(value, 2);
			}
			return formatNumber(value, 4);
		}
		if (typeof value === "boolean") return value ? "yes" : "no";
		if (typeof value === "string") return value;
		return String(value);
	}

	/** Map raw backend keys to institutional display labels. */
	const ADVISOR_KEY_LABELS: Record<string, string> = {
		portfolio_id: "Portfolio",
		profile: "Profile",
		current_cvar_95: "Current Tail Loss (95%)",
		cvar_limit: "Tail Loss Limit",
		cvar_gap: "Risk Budget Gap",
		detail_endpoint: "Detail Endpoint",
		note: "Note",
	};

	function advisorKeyLabel(key: string): string {
		return ADVISOR_KEY_LABELS[key] ?? key.replace(/_/g, " ");
	}
</script>

<svelte:boundary>
	<div class="at-root">
		{#if !run}
			<div class="at-empty">Run construction to see advisor analysis</div>
		{:else if !narrative}
			<div class="at-empty">No narrative in this construction run</div>
		{:else}
			<!-- Headline -->
			{#if narrative.headline}
				<h3 class="at-headline">{narrative.headline}</h3>
			{/if}

			<!-- Key points -->
			{#if narrative.key_points && narrative.key_points.length > 0}
				<ul class="at-points">
					{#each narrative.key_points as point}
						<li class="at-point">{point}</li>
					{/each}
				</ul>
			{/if}

			<!-- Ex-ante metrics strip -->
			{#if metrics}
				<div class="at-metrics">
					{#each METRIC_DISPLAY as m (m.key)}
						{@const value = metrics[m.key]}
						{@const delta = deltas?.[m.key]}
						<div class="at-stat">
							<span class="at-stat-label">{m.label}</span>
							<span class="at-stat-value">
								{value != null ? m.format(value) : "\u2014"}
							</span>
							{#if delta != null && delta !== 0}
								<span
									class="at-stat-delta"
									class:at-stat-delta--pos={delta > 0}
									class:at-stat-delta--neg={delta < 0}
								>
									{delta > 0 ? "+" : ""}{formatNumber(delta * 100, 2)}pp
								</span>
							{/if}
						</div>
					{/each}
				</div>
			{/if}

			<!-- Holding changes -->
			{#if holdingChanges.length > 0}
				<section class="at-changes">
					<header class="at-section-kicker">Holding Changes</header>
					<table class="at-changes-table">
						<thead>
							<tr>
								<th scope="col">Fund</th>
								<th scope="col" class="at-num">From</th>
								<th scope="col" class="at-num">To</th>
								<th scope="col" class="at-num">Delta</th>
							</tr>
						</thead>
						<tbody>
							{#each holdingChanges as change (change.instrument_id)}
								<tr>
									<td class="at-fund-name">{change.name}</td>
									<td class="at-num">
										{change.prev_weight != null
											? formatPercent(change.prev_weight, 2)
											: "\u2014"}
									</td>
									<td class="at-num">{formatPercent(change.next_weight, 2)}</td>
									<td
										class="at-num"
										class:at-delta-pos={change.delta > 0}
										class:at-delta-neg={change.delta < 0}
									>
										{change.delta > 0 ? "+" : ""}{formatPercent(change.delta, 2)}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</section>
			{/if}

			<!-- Advisor notes -->
			{#if advisorEntries.length > 0}
				<section class="at-advisor">
					<header class="at-section-kicker">Construction Notes</header>
					<dl class="at-advisor-grid">
						{#each advisorEntries as [key, value] (key)}
							<div class="at-advisor-item">
								<dt class="at-advisor-key">{advisorKeyLabel(key)}</dt>
								<dd class="at-advisor-value">{formatAdvisorValue(key, value)}</dd>
							</div>
						{/each}
					</dl>
				</section>
			{/if}
		{/if}
	</div>

	{#snippet failed(err: unknown)}
		<div class="at-empty">Advisor panel failed to render</div>
	{/snippet}
</svelte:boundary>

<style>
	.at-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.at-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	/* ── Headline ─────────────────────────────────────── */

	.at-headline {
		margin: 0;
		font-size: var(--terminal-text-14);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		line-height: var(--terminal-leading-snug);
	}

	/* ── Key points ───────────────────────────────────── */

	.at-points {
		margin: 0;
		padding-left: var(--terminal-space-4);
		list-style: disc;
	}

	.at-point {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		line-height: var(--terminal-leading-normal);
		margin-bottom: var(--terminal-space-1);
	}

	/* ── Metrics strip ────────────────────────────────── */

	.at-metrics {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) 0;
		border-top: var(--terminal-border-hairline);
		border-bottom: var(--terminal-border-hairline);
	}

	.at-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.at-stat-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}

	.at-stat-value {
		font-size: var(--terminal-text-14);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--terminal-fg-primary);
	}

	.at-stat-delta {
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
	}

	.at-stat-delta--pos {
		color: var(--terminal-status-success);
	}

	.at-stat-delta--neg {
		color: var(--terminal-status-error);
	}

	/* ── Holding changes ──────────────────────────────── */

	.at-section-kicker {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		margin-bottom: var(--terminal-space-2);
	}

	.at-changes-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--terminal-text-11);
	}

	.at-changes-table th,
	.at-changes-table td {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
		text-align: left;
	}

	.at-changes-table thead th {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}

	.at-fund-name {
		color: var(--terminal-fg-primary);
		font-weight: 600;
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.at-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.at-delta-pos {
		color: var(--terminal-status-success);
	}

	.at-delta-neg {
		color: var(--terminal-status-error);
	}

	/* ── Advisor notes ────────────────────────────────── */

	.at-advisor {
		padding: var(--terminal-space-3);
		border: var(--terminal-border-hairline);
	}

	.at-advisor-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--terminal-space-2) var(--terminal-space-4);
		margin: 0;
	}

	.at-advisor-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.at-advisor-key {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: capitalize;
		color: var(--terminal-fg-tertiary);
	}

	.at-advisor-value {
		margin: 0;
		font-size: var(--terminal-text-12);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--terminal-fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
