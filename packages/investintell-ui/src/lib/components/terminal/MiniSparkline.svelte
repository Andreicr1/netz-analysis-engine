<!--
	MiniSparkline.svelte
	====================

	Tabular SVG polyline — 60x18 default footprint designed for in-row
	rendering in dense grids. Pure <polyline>; no lightweight-charts,
	no tooltip, no hover. Consumers overlay a value label in the row,
	not the sparkline.

	Tone auto-computes from first-vs-last when omitted: up if last > first,
	down if last < first, neutral if equal. Empty/single-point arrays
	render an empty <svg> so consumers can unconditionally mount.

	Source: docs/plans/2026-04-19-netz-terminal-parity-builder-macro-screener.md §B.2.
-->
<script lang="ts">
	export type MiniSparklineTone = "up" | "down" | "neutral";

	interface Props {
		data: number[];
		width?: number;
		height?: number;
		tone?: MiniSparklineTone;
		strokeWidth?: number;
		ariaLabel?: string;
		class?: string;
	}

	let {
		data,
		width = 60,
		height = 18,
		tone,
		strokeWidth = 1,
		ariaLabel,
		class: className,
	}: Props = $props();

	const resolvedTone = $derived<MiniSparklineTone>(
		tone ?? computeTone(data),
	);

	function computeTone(series: number[]): MiniSparklineTone {
		if (series.length < 2) return "neutral";
		const first = series[0]!;
		const last = series[series.length - 1]!;
		if (last > first) return "up";
		if (last < first) return "down";
		return "neutral";
	}

	const points = $derived(buildPoints(data, width, height, strokeWidth));

	function buildPoints(
		series: number[],
		w: number,
		h: number,
		stroke: number,
	): string {
		if (series.length < 2) return "";
		const pad = Math.max(1, stroke / 2);
		const innerW = w - pad * 2;
		const innerH = h - pad * 2;
		let min = Infinity;
		let max = -Infinity;
		for (const v of series) {
			if (v < min) min = v;
			if (v > max) max = v;
		}
		const span = max - min || 1;
		const step = series.length > 1 ? innerW / (series.length - 1) : 0;
		const coords: string[] = [];
		for (let i = 0; i < series.length; i++) {
			const v = series[i]!;
			const x = pad + step * i;
			const y = pad + innerH - ((v - min) / span) * innerH;
			coords.push(`${x.toFixed(2)},${y.toFixed(2)}`);
		}
		return coords.join(" ");
	}
</script>

<svg
	class="mini-sparkline mini-sparkline--{resolvedTone} {className ?? ''}"
	viewBox="0 0 {width} {height}"
	width={width}
	height={height}
	role="img"
	aria-label={ariaLabel ?? ''}
	aria-hidden={ariaLabel ? undefined : true}
	preserveAspectRatio="none"
>
	{#if points}
		<polyline
			points={points}
			fill="none"
			stroke="currentColor"
			stroke-width={strokeWidth}
			stroke-linejoin="round"
			stroke-linecap="round"
			vector-effect="non-scaling-stroke"
		/>
	{/if}
</svg>

<style>
	.mini-sparkline {
		display: inline-block;
		vertical-align: middle;
		flex-shrink: 0;
	}
	.mini-sparkline--up {
		color: var(--terminal-status-success);
	}
	.mini-sparkline--down {
		color: var(--terminal-status-error);
	}
	.mini-sparkline--neutral {
		color: var(--terminal-fg-tertiary);
	}
</style>
