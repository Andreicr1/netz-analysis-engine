<script lang="ts">
	import type { RegimePinState, RegimeTrailPoint } from "./regime-plot-store.svelte";

	interface Props {
		activeRegime: string;
		livePin: RegimePinState;
		simulatedPin: RegimePinState | null;
		trail: RegimeTrailPoint[];
		onSimulate: (pin: RegimePinState | null) => void;
	}

	let { activeRegime, livePin, simulatedPin, trail, onSimulate }: Props = $props();

	const SIZE = 540;
	const PAD_LEFT = 142;
	const PAD_TOP = 68;
	const PLOT = 344;
	const CX = PAD_LEFT + PLOT / 2;
	const CY = PAD_TOP + PLOT / 2;
	const STEP = 0.1;

	let svgEl = $state<SVGSVGElement | null>(null);
	let dragging = $state(false);

	function toPx(g: number, i: number): { x: number; y: number } {
		return {
			x: PAD_LEFT + ((g + 1) / 2) * PLOT,
			y: PAD_TOP + (1 - (i + 1) / 2) * PLOT,
		};
	}

	function fromPx(x: number, y: number): RegimePinState {
		const g = Math.max(-1, Math.min(1, ((x - PAD_LEFT) / PLOT) * 2 - 1));
		const i = Math.max(-1, Math.min(1, 1 - ((y - PAD_TOP) / PLOT) * 2));
		return { g: Math.round(g * 100) / 100, i: Math.round(i * 100) / 100 };
	}

	const pin = $derived(simulatedPin ?? livePin);
	const pinPx = $derived(toPx(pin.g, pin.i));
	const livePx = $derived(toPx(livePin.g, livePin.i));
	const isSimulating = $derived(simulatedPin !== null);
	const trailPoints = $derived(trail.map((point) => toPx(point.g, point.i)));
	const trailPolyline = $derived(trailPoints.map((point) => `${point.x},${point.y}`).join(" "));
	const activeLabelX = $derived(pinPx.x < CX ? pinPx.x + 14 : pinPx.x - 14);
	const activeLabelAnchor = $derived(pinPx.x < CX ? "start" : "end");
	const liveLabelX = $derived(livePx.x < CX ? livePx.x + 14 : livePx.x - 14);
	const liveLabelAnchor = $derived(livePx.x < CX ? "start" : "end");

	const gridFractions = [0, 0.25, 0.5, 0.75, 1];
	const qLabels = [
		{ label: "STAGFLATION", x: CX - PLOT / 4, y: PAD_TOP + 18, color: "var(--ii-danger)" },
		{ label: "OVERHEATING", x: CX + PLOT / 4, y: PAD_TOP + 18, color: "var(--ii-brand-primary)" },
		{ label: "REFLATION", x: CX - PLOT / 4, y: PAD_TOP + PLOT - 14, color: "#6689bc" },
		{ label: "GOLDILOCKS", x: CX + PLOT / 4, y: PAD_TOP + PLOT - 14, color: "var(--ii-success)" },
	] as const;

	function svgCoords(e: PointerEvent): { x: number; y: number } | null {
		if (!svgEl) return null;
		const rect = svgEl.getBoundingClientRect();
		return {
			x: (e.clientX - rect.left) * (SIZE / rect.width),
			y: (e.clientY - rect.top) * (SIZE / rect.height),
		};
	}

	function handlePointerDown(e: PointerEvent) {
		e.preventDefault();
		svgEl?.setPointerCapture(e.pointerId);
		dragging = true;
		const coords = svgCoords(e);
		if (coords) onSimulate(fromPx(coords.x, coords.y));
	}

	function handlePointerMove(e: PointerEvent) {
		if (!dragging) return;
		const coords = svgCoords(e);
		if (coords) onSimulate(fromPx(coords.x, coords.y));
	}

	function handlePointerUp(e: PointerEvent) {
		dragging = false;
		if (svgEl?.hasPointerCapture(e.pointerId)) svgEl.releasePointerCapture(e.pointerId);
	}

	function handleKeydown(e: KeyboardEvent) {
		const base = simulatedPin ?? livePin;
		let next: RegimePinState | null = null;
		switch (e.key) {
			case "ArrowRight":
				next = { g: Math.min(1, base.g + STEP), i: base.i };
				break;
			case "ArrowLeft":
				next = { g: Math.max(-1, base.g - STEP), i: base.i };
				break;
			case "ArrowUp":
				next = { g: base.g, i: Math.min(1, base.i + STEP) };
				break;
			case "ArrowDown":
				next = { g: base.g, i: Math.max(-1, base.i - STEP) };
				break;
			case "Escape":
				if (simulatedPin) {
					e.preventDefault();
					onSimulate(null);
				}
				return;
			case "Enter":
			case " ":
				next = base;
				break;
			default:
				return;
		}
		e.preventDefault();
		onSimulate(next);
	}
</script>

<div class="rp-root">
	<header class="rp-header">
		<span class="rp-title">REGIME MATRIX · GROWTH x INFLATION</span>
		<span class="rp-active">{activeRegime}</span>
		{#if isSimulating}
			<button type="button" class="rp-reset" onclick={() => onSimulate(null)}>RESET</button>
		{/if}
	</header>

	{#if isSimulating}
		<div class="rp-banner" role="status" aria-live="polite">SIMULATION - DOES NOT PERSIST</div>
	{/if}

	<button
		type="button"
		class="rp-stage"
		aria-label="Regime coordinate plot"
		onpointerdown={handlePointerDown}
		onpointermove={handlePointerMove}
		onpointerup={handlePointerUp}
		onpointercancel={handlePointerUp}
		onkeydown={handleKeydown}
		style:cursor={dragging ? "grabbing" : "crosshair"}
	>
		<svg bind:this={svgEl} viewBox="0 0 {SIZE} {SIZE}" class="rp-svg" aria-hidden="true">
			<rect x={PAD_LEFT} y={PAD_TOP} width={PLOT / 2} height={PLOT / 2} fill="rgba(255,92,122,0.075)" />
			<rect x={CX} y={PAD_TOP} width={PLOT / 2} height={PLOT / 2} fill="rgba(255,150,90,0.075)" />
			<rect x={PAD_LEFT} y={CY} width={PLOT / 2} height={PLOT / 2} fill="rgba(102,137,188,0.07)" />
			<rect x={CX} y={CY} width={PLOT / 2} height={PLOT / 2} fill="rgba(61,211,154,0.07)" />

			{#each gridFractions as f}
				<line x1={PAD_LEFT + f * PLOT} y1={PAD_TOP} x2={PAD_LEFT + f * PLOT} y2={PAD_TOP + PLOT} stroke="var(--ii-terminal-hair)" stroke-width="0.7" stroke-dasharray="2 5" />
				<line x1={PAD_LEFT} y1={PAD_TOP + f * PLOT} x2={PAD_LEFT + PLOT} y2={PAD_TOP + f * PLOT} stroke="var(--ii-terminal-hair)" stroke-width="0.7" stroke-dasharray="2 5" />
			{/each}

			<line x1={CX} y1={PAD_TOP} x2={CX} y2={PAD_TOP + PLOT} stroke="#6689bc" stroke-width="0.8" opacity="0.5" />
			<line x1={PAD_LEFT} y1={CY} x2={PAD_LEFT + PLOT} y2={CY} stroke="#6689bc" stroke-width="0.8" opacity="0.5" />
			<rect x={PAD_LEFT} y={PAD_TOP} width={PLOT} height={PLOT} fill="none" stroke="var(--ii-border-subtle)" stroke-width="1" />

			{#each qLabels as q}
				<text x={q.x} y={q.y} text-anchor="middle" dominant-baseline="middle" font-family="var(--ii-font-mono)" font-size="10" font-weight="700" letter-spacing="0.12em" fill={q.color} pointer-events="none">{q.label}</text>
			{/each}

			<text x={PAD_LEFT + 12} y={CY - 8} text-anchor="start" font-family="var(--ii-font-mono)" font-size="9" letter-spacing="0.1em" fill="var(--ii-text-muted)">INFLATION ↑</text>
			<text x={PAD_LEFT + 12} y={CY + 16} text-anchor="start" font-family="var(--ii-font-mono)" font-size="9" letter-spacing="0.1em" fill="var(--ii-text-muted)">DISINFL ↓</text>
			<text x={CX - 8} y={PAD_TOP + PLOT + 34} text-anchor="end" font-family="var(--ii-font-mono)" font-size="9" letter-spacing="0.1em" fill="var(--ii-text-muted)">← CONTRACTION</text>
			<text x={CX + 8} y={PAD_TOP + PLOT + 34} font-family="var(--ii-font-mono)" font-size="9" letter-spacing="0.1em" fill="var(--ii-text-muted)">GROWTH →</text>

			{#if trailPoints.length >= 2}
				<polyline points={trailPolyline} fill="none" stroke="var(--ii-text-muted)" stroke-width="1" stroke-dasharray="3 3" opacity="0.55" pointer-events="none" />
				{#each trailPoints as pt, idx}
					{@const opacity = 0.2 + (idx / trailPoints.length) * 0.55}
					<circle cx={pt.x} cy={pt.y} r="3" fill="var(--ii-text-muted)" {opacity} pointer-events="none" />
				{/each}
			{/if}

			{#if !isSimulating}
				<circle cx={livePx.x} cy={livePx.y} r="11" fill="var(--ii-brand-primary)" opacity="0.24" pointer-events="none" />
				<circle cx={livePx.x} cy={livePx.y} r="6" fill="var(--ii-brand-primary)" stroke="var(--ii-bg)" stroke-width="2" pointer-events="none" />
				<text x={liveLabelX} y={livePx.y + 4} text-anchor={liveLabelAnchor} font-family="var(--ii-font-mono)" font-size="10" font-weight="700" fill="var(--ii-text-primary)" pointer-events="none">NOW</text>
			{:else}
				<circle cx={livePx.x} cy={livePx.y} r="4" fill="none" stroke="var(--ii-text-secondary)" stroke-width="1" stroke-dasharray="2 2" opacity="0.45" pointer-events="none" />
				<circle cx={pinPx.x} cy={pinPx.y} r="11" fill="var(--ii-brand-primary)" opacity="0.24" pointer-events="none" />
				<circle cx={pinPx.x} cy={pinPx.y} r="6" fill="var(--ii-brand-primary)" stroke="var(--ii-bg)" stroke-width="2" pointer-events="none" />
				<text x={activeLabelX} y={pinPx.y + 4} text-anchor={activeLabelAnchor} font-family="var(--ii-font-mono)" font-size="10" font-weight="700" fill="var(--ii-text-primary)" pointer-events="none">SIM</text>
			{/if}
		</svg>
	</button>

	{#if isSimulating && simulatedPin}
		<div class="rp-coords">G {simulatedPin.g >= 0 ? "+" : ""}{simulatedPin.g.toFixed(2)} / I {simulatedPin.i >= 0 ? "+" : ""}{simulatedPin.i.toFixed(2)}</div>
	{/if}
</div>

<style>
	.rp-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--ii-surface);
		font-family: var(--ii-font-mono);
	}
	.rp-header {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 32px;
		padding: 0 14px;
	}
	.rp-title {
		color: var(--ii-text-muted);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.rp-active {
		margin-left: auto;
		color: var(--ii-brand-primary);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.rp-reset {
		padding: 1px 8px;
		background: transparent;
		border: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-secondary);
		font: inherit;
		font-size: 10px;
		cursor: pointer;
	}
	.rp-banner {
		margin: 0 14px;
		padding: 3px 8px;
		border-left: 3px solid var(--ii-brand-primary);
		background: var(--ii-bg);
		color: var(--ii-brand-primary);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.rp-stage {
		display: block;
		width: min(100%, 620px);
		height: min(100%, 620px);
		margin: auto;
		padding: 0;
		border: 0;
		background: transparent;
		touch-action: none;
	}
	.rp-stage:focus-visible {
		outline: 1px solid var(--ii-brand-primary);
		outline-offset: 2px;
	}
	.rp-svg {
		display: block;
		width: 100%;
		height: 100%;
	}
	.rp-coords {
		padding: 2px 14px 10px;
		color: var(--ii-brand-primary);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		letter-spacing: var(--ii-terminal-tr-caps);
		text-align: right;
	}
</style>
