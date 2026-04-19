<!--
  CoverageGapPanel — PR-A22. Surfaced when a construction run aborts
  pre-solve with ``winner_signal === "block_coverage_insufficient"``.

  Smart-backend / dumb-frontend: the backend owns the prose
  (``operator_message``) and the per-block gap list
  (``coverage_report``). This component just tables the data and
  emits a CTA link to the approved-universe editor with a
  ``?highlight=<block_id>`` hint the target page may consume later
  (PR-A22 only emits the link).
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { blockLabel } from "$wealth/constants/blocks";
	import type {
		CoverageReport,
		OperatorMessage,
	} from "$wealth/types/cascade-telemetry";

	interface Props {
		report: CoverageReport;
		message: OperatorMessage | null;
		universeHref?: string;
	}

	let {
		report,
		message,
		universeHref = "/portfolio",
	}: Props = $props();

	function gapHref(blockId: string): string {
		const separator = universeHref.includes("?") ? "&" : "?";
		return `${universeHref}${separator}highlight=${encodeURIComponent(blockId)}`;
	}
</script>

<section class="cgp-root" data-testid="coverage-gap-panel">
	<header class="cgp-header">
		<h2 class="cgp-title">
			Coverage insufficient — {formatPercent(
				report.total_target_weight_at_risk,
				1,
			)} of mandate uncovered
		</h2>
		{#if message}
			<p class="cgp-subtitle">{message.title}</p>
		{/if}
	</header>

	<table class="cgp-table">
		<thead>
			<tr>
				<th scope="col">Block</th>
				<th scope="col" class="cgp-num">Target weight</th>
				<th scope="col" class="cgp-num">Catalog candidates</th>
				<th scope="col">Examples</th>
				<th scope="col" class="cgp-cta-col">Action</th>
			</tr>
		</thead>
		<tbody>
			{#each report.gaps as gap (gap.block_id)}
				<tr>
					<td>
						<span class="cgp-block-name">{blockLabel(gap.block_id) || gap.block_id}</span>
						<span class="cgp-block-id">{gap.block_id}</span>
					</td>
					<td class="cgp-num">{formatPercent(gap.target_weight, 1)}</td>
					<td class="cgp-num">{formatNumber(gap.catalog_candidates_available, 0)}</td>
					<td>
						{#if gap.example_tickers.length > 0}
							<span class="cgp-tickers">{gap.example_tickers.join(", ")}</span>
						{:else}
							<span class="cgp-empty">no catalog suggestions</span>
						{/if}
					</td>
					<td>
						<a
							class="cgp-cta"
							href={gapHref(gap.block_id)}
							data-block-id={gap.block_id}
						>
							Review universe
						</a>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>

	{#if message}
		<p class="cgp-body">{message.body}</p>
	{/if}
</section>

<style>
	.cgp-root {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 24px;
		border-left: 3px solid var(--terminal-status-error);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}
	.cgp-header {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.cgp-title {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}
	.cgp-subtitle {
		margin: 0;
		font-size: 12px;
		color: var(--terminal-fg-secondary);
	}
	.cgp-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.cgp-table th,
	.cgp-table td {
		padding: 8px 12px;
		text-align: left;
		border-bottom: 1px solid var(--terminal-border-subtle);
		vertical-align: middle;
	}
	.cgp-table thead th {
		color: var(--terminal-fg-muted);
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 600;
	}
	.cgp-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.cgp-cta-col {
		text-align: right;
	}
	.cgp-block-name {
		display: block;
		color: var(--terminal-fg-primary);
	}
	.cgp-block-id {
		display: block;
		font-size: 10px;
		color: var(--terminal-fg-muted);
	}
	.cgp-tickers {
		color: var(--terminal-fg-secondary);
	}
	.cgp-empty {
		color: var(--terminal-fg-muted);
		font-style: italic;
	}
	.cgp-cta {
		color: var(--terminal-status-info, var(--terminal-fg-primary));
		text-decoration: underline;
		font-size: 12px;
	}
	.cgp-cta:hover,
	.cgp-cta:focus-visible {
		text-decoration: none;
	}
	.cgp-body {
		margin: 0;
		white-space: pre-wrap;
		font-size: 11px;
		line-height: 1.5;
		color: var(--terminal-fg-secondary);
	}
</style>
