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

	const SIZE = 360;
	const PAD = 28;
	const PLOT = SIZE - PAD * 2;
	const CX = PAD + PLOT / 2;
	const CY = PAD + PLOT / 2;
	const STEP = 0.1;

	let svgEl = $state<SVGSVGElement | null>(null);
	let dragging = $state(false);

	function toPx(g: number, i: number): { x: number; y: number } {
		return {
			x: PAD + ((g + 1) / 2) * PLOT,
			y: PAD + (1 - (i + 1) / 2) * PLOT,
		};
	}

	function fromPx(x: number, y: number): RegimePinState {
		const g = Math.max(-1, Math.min(1, ((x - PAD) / PLOT) * 2 - 1));
		const i = Math.max(-1, Math.min(1, 1 - ((y - PAD) / PLOT) * 2));
		return { g: Math.round(g * 100) / 100, i: Math.round(i * 100) / 100 };
	}

	const pin = $derived(simulatedPin ?? livePin);
	const pinPx = $derived(toPx(pin.g, pin.i));
	const livePx = $derived(toPx(livePin.g, livePin.i));
	const isSimulating = $derived(simulatedPin !== null);
	const trailPoints = $derived(trail.map((point) => toPx(point.g, point.i)));
	const trailPolyline = $derived(trailPoints.map((point) => `${point.x},${point.y}`).join(" "));

	const Q_LABELS = [
		{ label: "GOLDILOCKS", x: CX + PLOT / 4, y: CY + PLOT / 4, color: "var(--terminal-accent-green, #4adf86)" },
		{ label: "OVERHEATING", x: CX + PLOT / 4, y: CY - PLOT / 4, color: "var(--terminal-accent-amber)" },
		{ label: "STAGFLATION", x: CX - PLOT / 4, y: CY - PLOT / 4, color: "var(--terminal-accent-red, #f87171)" },
		{ label: "REFLATION", x: CX - PLOT / 4, y: CY + PLOT / 4, color: "#6689bc" },
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
		<span class="rp-title">REGIME MATRIX</span>
		<span class="rp-active">ACTIVE {activeRegime}</span>
		{#if isSimulating}
			<button type="button" class="rp-reset" onclick={() => onSimulate(null)}>RESET</button>
		{/if}
	</header>

	{#if isSimulating}
		<div class="rp-banner" role="status" aria-live="polite">SIMULATION - DOES NOT PERSIST</div>
	{/if}

	<svg
		bind:this={svgEl}
		viewBox="0 0 {SIZE} {SIZE}"
		class="rp-svg"
		role="application"
		aria-label="Regime coordinate plot"
		tabindex="0"
		onpointerdown={handlePointerDown}
		onpointermove={handlePointerMove}
		onpointerup={handlePointerUp}
		onpointercancel={handlePointerUp}
		onkeydown={handleKeydown}
		style:cursor={dragging ? "grabbing" : "crosshair"}
	>
		<rect x={CX} y={PAD} width={PLOT / 2} height={PLOT / 2} fill="#4adf8610" />
		<rect x={CX} y={CY} width={PLOT / 2} height={PLOT / 2} fill="#f6c90e10" />
		<rect x={PAD} y={PAD} width={PLOT / 2} height={PLOT / 2} fill="#f8717110" />
		<rect x={PAD} y={CY} width={PLOT / 2} height={PLOT / 2} fill="#6689bc10" />
		<line x1={CX} y1={PAD} x2={CX} y2={PAD + PLOT} stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" stroke-dasharray="3 4" opacity="0.4" />
		<line x1={PAD} y1={CY} x2={PAD + PLOT} y2={CY} stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" stroke-dasharray="3 4" opacity="0.4" />
		<rect x={PAD} y={PAD} width={PLOT} height={PLOT} fill="none" stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" opacity="0.4" />

		{#each Q_LABELS as q}
			<text x={q.x} y={q.y} text-anchor="middle" dominant-baseline="middle" font-family="var(--terminal-font-mono)" font-size="9" font-weight="600" fill={q.color} opacity="0.5" pointer-events="none">{q.label}</text>
		{/each}

		{#if trailPoints.length >= 2}
			<polyline points={trailPolyline} fill="none" stroke="var(--terminal-accent-amber)" stroke-width="1" stroke-dasharray="2 3" opacity="0.35" pointer-events="none" />
			{#each trailPoints as pt, idx}
				{@const opacity = 0.1 + (idx / trailPoints.length) * 0.4}
				<circle cx={pt.x} cy={pt.y} r="2" fill="var(--terminal-accent-amber)" {opacity} pointer-events="none" />
			{/each}
		{/if}

		{#if !isSimulating}
			<circle cx={livePx.x} cy={livePx.y} r="5" fill="var(--terminal-accent-amber)" stroke="var(--terminal-bg-panel)" stroke-width="1.5" pointer-events="none" />
		{:else}
			<circle cx={livePx.x} cy={livePx.y} r="4" fill="none" stroke="var(--terminal-fg-secondary)" stroke-width="1" stroke-dasharray="2 2" opacity="0.4" pointer-events="none" />
			<circle cx={pinPx.x} cy={pinPx.y} r="6" fill="var(--terminal-accent-amber)" stroke="var(--terminal-bg-panel)" stroke-width="2" pointer-events="none" />
			<text x={pinPx.x} y={pinPx.y - 10} text-anchor="middle" font-family="var(--terminal-font-mono)" font-size="8" fill="var(--terminal-accent-amber)" pointer-events="none">SIM</text>
		{/if}
	</svg>

	{#if isSimulating && simulatedPin}
		<div class="rp-coords">G {simulatedPin.g >= 0 ? "+" : ""}{simulatedPin.g.toFixed(2)} / I {simulatedPin.i >= 0 ? "+" : ""}{simulatedPin.i.toFixed(2)}</div>
	{/if}
</div>

<style>
	.rp-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}
	.rp-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3) 0;
	}
	.rp-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.rp-active {
		margin-left: auto;
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.rp-reset {
		padding: 1px var(--terminal-space-2);
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
		font: inherit;
		font-size: var(--terminal-text-10);
		cursor: pointer;
	}
	.rp-banner {
		margin: 0 var(--terminal-space-3);
		padding: 2px var(--terminal-space-2);
		border-left: 3px solid var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.rp-svg {
		display: block;
		width: 100%;
		height: auto;
		aspect-ratio: 1 / 1;
		touch-action: none;
	}
	.rp-svg:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
	.rp-coords {
		padding: 2px var(--terminal-space-3) var(--terminal-space-2);
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-11);
		font-variant-numeric: tabular-nums;
		letter-spacing: var(--terminal-tracking-caps);
		text-align: right;
	}
</style>
