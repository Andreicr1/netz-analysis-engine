<!--
  LivePortfolioSidebar — Phase 8 Live Workbench left rail.

  Persistent list of live portfolios shown on the left of the
  /portfolio/live workbench. Mirrors the density of the
  AnalyticsSubjectList but is tailored to monitoring: state chip
  always visible, inception date stamped as secondary text, selected
  row carries the brand-blue accent.

  Pure presentation — the parent (LiveWorkbenchShell) owns the
  ``selectedId`` and ``onSelect`` contract. No workspace reads, no
  localStorage, no fetches (DL15 — all state is URL + in-memory).
-->
<script lang="ts">
	import { formatShortDate } from "@investintell/ui";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	interface Props {
		portfolios: readonly ModelPortfolio[];
		selectedId: string | null;
		onSelect: (portfolio: ModelPortfolio) => void;
	}

	let { portfolios, selectedId, onSelect }: Props = $props();
</script>

<aside class="lps-root" aria-label="Live portfolios">
	<header class="lps-header">
		<span class="lps-kicker">Live</span>
		<span class="lps-title">Portfolios</span>
		<span class="lps-count">{portfolios.length}</span>
	</header>

	<ul class="lps-list" role="listbox" aria-label="Live portfolios">
		{#each portfolios as portfolio (portfolio.id)}
			{@const isSelected = selectedId === portfolio.id}
			<li>
				<button
					type="button"
					class="lps-row"
					class:lps-row--selected={isSelected}
					role="option"
					aria-selected={isSelected}
					onclick={() => onSelect(portfolio)}
				>
					<span class="lps-name">{portfolio.display_name}</span>
					<span class="lps-meta">
						<span class="lps-profile">{portfolio.profile}</span>
						{#if portfolio.inception_date}
							<span class="lps-date">
								Since {formatShortDate(portfolio.inception_date)}
							</span>
						{/if}
					</span>
					<span class="lps-state-dot" aria-hidden="true"></span>
				</button>
			</li>
		{/each}
	</ul>
</aside>

<style>
	.lps-root {
		display: flex;
		flex-direction: column;
		gap: 12px;
		height: 100%;
		min-height: 0;
		padding: 16px 12px;
		background: #141519;
		border-right: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.lps-header {
		display: grid;
		grid-template-columns: auto 1fr auto;
		grid-template-rows: auto auto;
		column-gap: 8px;
		align-items: baseline;
		padding: 4px 8px 10px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.lps-kicker {
		grid-column: 1;
		grid-row: 1;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.lps-title {
		grid-column: 1 / span 2;
		grid-row: 2;
		font-size: 14px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.lps-count {
		grid-column: 3;
		grid-row: 1 / span 2;
		align-self: center;
		padding: 2px 8px;
		font-size: 10px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
		background: rgba(255, 255, 255, 0.05);
		border-radius: 9999px;
	}

	.lps-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
		overflow-y: auto;
		min-height: 0;
		flex: 1;
	}

	.lps-row {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-rows: auto auto;
		column-gap: 8px;
		align-items: baseline;
		width: 100%;
		padding: 10px 12px;
		border: 1px solid transparent;
		border-radius: 8px;
		background: transparent;
		color: var(--ii-text-secondary, #cbccd1);
		font-family: inherit;
		text-align: left;
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.lps-row:hover:not(.lps-row--selected) {
		background: rgba(255, 255, 255, 0.04);
		color: var(--ii-text-primary, #ffffff);
	}
	.lps-row--selected {
		background: rgba(1, 119, 251, 0.12);
		border-color: var(--ii-primary, #0177fb);
		color: var(--ii-text-primary, #ffffff);
	}

	.lps-name {
		grid-column: 1;
		grid-row: 1;
		font-size: 13px;
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lps-meta {
		grid-column: 1;
		grid-row: 2;
		display: flex;
		gap: 8px;
		align-items: baseline;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		min-width: 0;
	}
	.lps-profile {
		text-transform: capitalize;
	}
	.lps-date {
		font-variant-numeric: tabular-nums;
	}
	.lps-state-dot {
		grid-column: 2;
		grid-row: 1 / span 2;
		align-self: center;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--ii-success, #3fb950);
		box-shadow: 0 0 0 3px rgba(63, 185, 80, 0.12);
	}
</style>
