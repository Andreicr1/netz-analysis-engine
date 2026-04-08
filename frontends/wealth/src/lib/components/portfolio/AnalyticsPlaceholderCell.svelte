<!--
  AnalyticsPlaceholderCell — Phase 6 Block A visual validation cell.

  Renders a labelled empty box inside a ChartCard so Andrei can review
  the AnalysisGrid layout, container responsiveness, and chart card
  framing BEFORE Block B commits to ECharts integration.

  Per OD-26 — strict empty states. The placeholder is intentionally
  styled like a "coming soon" panel so visual validation cannot
  mistake it for a real (mocked) chart.
-->
<script lang="ts">
	interface Props {
		chartName: string;
		description?: string;
		span?: 1 | 2 | 3;
	}

	let { chartName, description, span = 1 }: Props = $props();
</script>

<div class="apc-root" data-span={span}>
	<div class="apc-icon" aria-hidden="true">
		<svg
			width="40"
			height="40"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<path d="M3 3v18h18" />
			<path d="M7 14l4-4 4 4 6-6" />
		</svg>
	</div>
	<p class="apc-name">{chartName}</p>
	{#if description}
		<p class="apc-description">{description}</p>
	{/if}
	<span class="apc-tag">Block B</span>
</div>

<style>
	.apc-root {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		min-height: 240px;
		padding: 24px;
		border: 1px dashed var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 6px;
		background: rgba(255, 255, 255, 0.015);
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", system-ui, sans-serif;
		text-align: center;
	}

	.apc-icon {
		color: var(--ii-text-muted, #85a0bd);
		opacity: 0.5;
	}

	.apc-name {
		margin: 0;
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-secondary, #cbccd1);
		letter-spacing: 0.01em;
	}

	.apc-description {
		margin: 0;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		max-width: 28ch;
		line-height: 1.5;
	}

	.apc-tag {
		margin-top: 4px;
		padding: 2px 8px;
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
		background: rgba(255, 255, 255, 0.04);
		border-radius: 999px;
	}
</style>
