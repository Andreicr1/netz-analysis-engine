<!--
  HoldingChangesList — top holding moves from the last construction
  run (weight deltas between the previous committed run and the
  current proposed weights). Rendered inside ConstructionNarrative.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";

	interface Change {
		instrument_id: string;
		name: string;
		prev_weight: number | null;
		next_weight: number;
		delta: number;
	}

	interface Props {
		changes: Change[];
		limit?: number;
	}

	let { changes, limit = 10 }: Props = $props();

	const top = $derived(
		[...changes]
			.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
			.slice(0, limit),
	);
</script>

<section class="hcl-root">
	<header class="hcl-header">
		<span class="hcl-kicker">Holding moves</span>
		<span class="hcl-title">Top weight changes</span>
	</header>

	{#if top.length === 0}
		<p class="hcl-empty">No holding changes vs previous run.</p>
	{:else}
		<ul class="hcl-list">
			{#each top as c (c.instrument_id)}
				{@const direction = c.delta > 0 ? "up" : c.delta < 0 ? "down" : "flat"}
				<li class="hcl-row">
					<span class="hcl-name">{c.name}</span>
					<span class="hcl-prev">
						{c.prev_weight === null ? "—" : formatPercent(c.prev_weight, 1)}
					</span>
					<span class="hcl-arrow" aria-hidden="true">→</span>
					<span class="hcl-next">{formatPercent(c.next_weight, 1)}</span>
					<span class="hcl-delta" data-direction={direction}>
						{direction === "up" ? "+" : ""}{formatPercent(c.delta, 1)}
					</span>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.hcl-root {
		display: flex;
		flex-direction: column;
		gap: 12px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.hcl-header {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.hcl-kicker {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.hcl-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.hcl-empty {
		margin: 0;
		font-size: 12px;
		font-style: italic;
		color: var(--ii-text-muted, #85a0bd);
	}
	.hcl-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.hcl-row {
		display: grid;
		grid-template-columns: 1fr auto auto auto auto;
		align-items: baseline;
		gap: 10px;
		padding: 6px 8px;
		background: rgba(255, 255, 255, 0.02);
		border-radius: 6px;
		font-size: 12px;
	}
	.hcl-name {
		color: var(--ii-text-primary, #ffffff);
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.hcl-prev,
	.hcl-next {
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-muted, #85a0bd);
	}
	.hcl-arrow {
		color: var(--ii-text-muted, #85a0bd);
	}
	.hcl-delta {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-muted, #85a0bd);
	}
	.hcl-delta[data-direction="up"] {
		color: var(--ii-success, #3fb950);
	}
	.hcl-delta[data-direction="down"] {
		color: var(--ii-danger, #fc1a1a);
	}
</style>
