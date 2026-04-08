<!--
  ChartCard — wrapper for a single analytical chart tile on the standalone
  Analysis page. Institutional aesthetic (no marketing flourish): 20px padding,
  13px uppercase-ish title, optional subtitle + actions slot.

  Span controls grid-column span inside an AnalysisGrid (1 / 2 / 3).
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		title: string;
		subtitle?: string;
		children: Snippet;
		actions?: Snippet;
		span?: 1 | 2 | 3;
		minHeight?: string;
	}

	let {
		title,
		subtitle,
		children,
		actions,
		span = 1,
		minHeight = "320px",
	}: Props = $props();
</script>

<section class="cc-card" data-span={span} style:min-height={minHeight}>
	<header class="cc-head">
		<div class="cc-titles">
			<h3 class="cc-title">{title}</h3>
			{#if subtitle}
				<p class="cc-subtitle">{subtitle}</p>
			{/if}
		</div>
		{#if actions}
			<div class="cc-actions">{@render actions()}</div>
		{/if}
	</header>
	<div class="cc-body">{@render children()}</div>
</section>

<style>
	.cc-card {
		display: flex;
		flex-direction: column;
		background: var(--ii-surface, #141519);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 6px;
		padding: 20px 24px 24px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.cc-card[data-span="2"] {
		grid-column: span 2;
	}
	.cc-card[data-span="3"] {
		grid-column: span 3;
	}
	.cc-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 16px;
		gap: 12px;
	}
	.cc-titles {
		min-width: 0;
	}
	.cc-title {
		font-size: 13px;
		font-weight: 600;
		margin: 0;
		color: var(--ii-text-primary);
		letter-spacing: 0.01em;
	}
	.cc-subtitle {
		font-size: 11px;
		color: var(--ii-text-muted);
		margin: 2px 0 0;
	}
	.cc-actions {
		flex-shrink: 0;
	}
	.cc-body {
		flex: 1;
		min-height: 0;
	}
</style>
