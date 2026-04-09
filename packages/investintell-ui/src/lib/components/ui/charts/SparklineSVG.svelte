<!--
  SparklineSVG — hyper-light pure-SVG sparkline glyph.

  Phase 9 Block C of the Wealth Live Workbench rebuild. This is
  explicitly NOT an ECharts component — a sparkline with no axes,
  no tooltip, and no interactivity is a glyph, not a chart. Using
  ECharts here would register a new canvas + theme + animation
  frame handler per KPI card, which is exactly the kind of reflow
  churn the Workbench density budget rules out.

  Contract:
    data  — array of numeric samples (the last N ticks from a
            LivePricePoller buffer, typically 20)
    color — stroke colour (CSS colour or CSS var reference)
    width / height — viewBox dimensions in pixels
    strokeWidth  — polyline stroke width
    padding      — inner vertical padding so the line never kisses
                   the top/bottom edges

  Zero external deps, zero side effects, zero runes that track
  anything outside ``$props`` and ``$derived``. Pure presentation.
-->
<script lang="ts">
	interface Props {
		data: readonly number[];
		color?: string;
		width?: number;
		height?: number;
		strokeWidth?: number;
		/** Inner vertical padding so the polyline never touches the edges. */
		padding?: number;
		ariaLabel?: string;
	}

	let {
		data,
		color = "currentColor",
		width = 80,
		height = 24,
		strokeWidth = 1.5,
		padding = 2,
		ariaLabel = "Sparkline",
	}: Props = $props();

	const points = $derived.by(() => {
		if (data.length < 2) return "";
		const n = data.length;
		let min = Infinity;
		let max = -Infinity;
		for (const v of data) {
			if (v < min) min = v;
			if (v > max) max = v;
		}
		// Guard against a perfectly flat series (range = 0) — map to
		// vertical midpoint instead of dividing by zero.
		const range = max - min || 1;
		const effectiveH = height - padding * 2;
		const stepX = n === 1 ? 0 : width / (n - 1);
		const parts: string[] = [];
		for (let i = 0; i < n; i++) {
			const x = i * stepX;
			// SVG origin is top-left — invert the y so higher values
			// sit higher in the visual.
			const y =
				padding + effectiveH - ((data[i]! - min) / range) * effectiveH;
			parts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
		}
		return parts.join(" ");
	});

	const hasData = $derived(data.length >= 2);
</script>

<svg
	class="sps-root"
	{width}
	{height}
	viewBox="0 0 {width} {height}"
	aria-label={ariaLabel}
	role="img"
	preserveAspectRatio="none"
>
	{#if hasData}
		<polyline
			fill="none"
			stroke={color}
			stroke-width={strokeWidth}
			stroke-linecap="round"
			stroke-linejoin="round"
			{points}
		/>
	{/if}
</svg>

<style>
	.sps-root {
		display: block;
		flex-shrink: 0;
	}
</style>
