<!--
	RegimeMatrix — 4x4 simulation grid (plan §B.4).

	Rows = stress axis (top: LOW_STRESS → bottom: CRISIS).
	Cols = growth axis (left: CONTRACTION → right: OVERHEAT).

	The user drags the active pin into any cell to preview the regime
	as-if. State is held in a page-local `MacroSimulationStore` — this
	component never writes to the global `pinnedRegime` store, never
	posts to the backend. Reset clears the simulation. A persistent
	SIMULATION banner makes the mode unmistakable.

	Accessibility: pointer drag primary; keyboard as fallback —
	arrow keys move the simulation cell, Enter/Space commits, Escape
	clears.
-->
<script lang="ts">
	import {
		STRESS_LABELS,
		GROWTH_LABELS,
		type RegimeCell,
	} from "./macro-simulation-store.svelte";

	interface Props {
		/** The real regime label (e.g. "RISK_OFF"). Rendered as context. */
		activeRegime: string;
		/** Current simulated cell, or null for no simulation. */
		simulatedCell: RegimeCell | null;
		/** Called on any simulation change — drag drop, keyboard, or reset. */
		onSimulate: (cell: RegimeCell | null) => void;
	}

	let { activeRegime, simulatedCell, onSimulate }: Props = $props();

	const ROWS = STRESS_LABELS.length;
	const COLS = GROWTH_LABELS.length;

	let gridEl: HTMLDivElement | null = $state(null);
	let draggingFrom = $state<RegimeCell | null>(null);
	let hoverCell = $state<RegimeCell | null>(null);

	const pinCell = $derived<RegimeCell>(simulatedCell ?? { row: 0, col: 0 });

	function cellsEqual(a: RegimeCell, b: RegimeCell): boolean {
		return a.row === b.row && a.col === b.col;
	}

	function handlePointerDownCell(row: number, col: number, event: PointerEvent) {
		event.preventDefault();
		draggingFrom = { row, col };
		hoverCell = { row, col };
		(event.target as HTMLElement).setPointerCapture(event.pointerId);
	}

	function handlePointerMove(event: PointerEvent) {
		if (!draggingFrom || !gridEl) return;
		const target = document.elementFromPoint(event.clientX, event.clientY);
		const cellEl = target?.closest<HTMLElement>("[data-cell]");
		if (!cellEl || !gridEl.contains(cellEl)) return;
		const row = Number(cellEl.dataset.row);
		const col = Number(cellEl.dataset.col);
		if (Number.isFinite(row) && Number.isFinite(col)) {
			hoverCell = { row, col };
		}
	}

	function handlePointerUp() {
		if (!draggingFrom) return;
		// Tap or drag both commit the hovered cell; if the user never
		// moved, hoverCell === draggingFrom so tap-to-simulate works.
		const target = hoverCell ?? draggingFrom;
		onSimulate(target);
		draggingFrom = null;
		hoverCell = null;
	}

	function handleReset() {
		onSimulate(null);
	}

	function handleGridKeydown(event: KeyboardEvent) {
		if (event.key === "Escape") {
			if (simulatedCell) {
				event.preventDefault();
				onSimulate(null);
			}
			return;
		}
		const base = simulatedCell ?? { row: 0, col: 0 };
		let next: RegimeCell | null = null;
		switch (event.key) {
			case "ArrowUp":
				next = { row: Math.max(0, base.row - 1), col: base.col };
				break;
			case "ArrowDown":
				next = { row: Math.min(ROWS - 1, base.row + 1), col: base.col };
				break;
			case "ArrowLeft":
				next = { row: base.row, col: Math.max(0, base.col - 1) };
				break;
			case "ArrowRight":
				next = { row: base.row, col: Math.min(COLS - 1, base.col + 1) };
				break;
			case "Enter":
			case " ":
				next = base;
				break;
			default:
				return;
		}
		event.preventDefault();
		onSimulate(next);
	}
</script>

<div class="rm-root">
	<header class="rm-header">
		<span class="rm-title">REGIME MATRIX</span>
		<span class="rm-context">ACTIVE {activeRegime}</span>
		<button
			type="button"
			class="rm-reset"
			onclick={handleReset}
			disabled={simulatedCell === null}
			aria-label="Reset regime simulation"
		>
			RESET
		</button>
	</header>

	{#if simulatedCell}
		<div class="rm-banner" role="status" aria-live="polite">
			SIMULATION — DOES NOT PERSIST
		</div>
	{/if}

	<div class="rm-axes">
		<span class="rm-axis rm-axis--rows">STRESS ↓</span>
		<span class="rm-axis rm-axis--cols">GROWTH →</span>
	</div>

	<div
		bind:this={gridEl}
		class="rm-grid"
		role="grid"
		aria-label="Regime simulation matrix"
		tabindex="0"
		onpointermove={handlePointerMove}
		onpointerup={handlePointerUp}
		onpointercancel={handlePointerUp}
		onkeydown={handleGridKeydown}
	>
		{#each Array(ROWS) as _, r (r)}
			<div class="rm-row" role="row">
				{#each Array(COLS) as _, c (c)}
					{@const isSim = simulatedCell !== null && cellsEqual(simulatedCell, { row: r, col: c })}
					{@const isHover = hoverCell !== null && cellsEqual(hoverCell, { row: r, col: c })}
					{@const isPinOrigin = simulatedCell === null && r === 0 && c === 0}
					<button
						type="button"
						class="rm-cell"
						class:rm-cell--sim={isSim}
						class:rm-cell--hover={isHover}
						class:rm-cell--origin={isPinOrigin}
						data-cell="1"
						data-row={r}
						data-col={c}
						role="gridcell"
						aria-selected={isSim}
						aria-label="Stress {STRESS_LABELS[r]} growth {GROWTH_LABELS[c]}"
						onpointerdown={(e) => handlePointerDownCell(r, c, e)}
					>
						{#if isSim}
							<span class="rm-pin" aria-hidden="true">●</span>
						{/if}
					</button>
				{/each}
			</div>
		{/each}
	</div>

	<div class="rm-labels">
		<span class="rm-label rm-label--stress-lo">{STRESS_LABELS[0]}</span>
		<span class="rm-label rm-label--stress-hi">{STRESS_LABELS[ROWS - 1]}</span>
		<span class="rm-label rm-label--growth-lo">{GROWTH_LABELS[0]}</span>
		<span class="rm-label rm-label--growth-hi">{GROWTH_LABELS[COLS - 1]}</span>
	</div>

	{#if simulatedCell}
		<footer class="rm-footer">
			<span class="rm-sim-coords">
				{STRESS_LABELS[pinCell.row]} · {GROWTH_LABELS[pinCell.col]}
			</span>
		</footer>
	{/if}
</div>

<style>
	.rm-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-3);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}

	.rm-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
	}
	.rm-title {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
		text-transform: uppercase;
	}
	.rm-context {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		margin-left: auto;
	}
	.rm-reset {
		padding: 2px var(--terminal-space-2);
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
		font-family: inherit;
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		cursor: pointer;
	}
	.rm-reset:disabled {
		color: var(--terminal-fg-disabled);
		border-color: var(--terminal-fg-disabled);
		cursor: not-allowed;
	}
	.rm-reset:not(:disabled):hover {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}

	.rm-banner {
		padding: 2px var(--terminal-space-2);
		background: var(--terminal-bg-panel-sunken);
		border-left: 3px solid var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rm-axes {
		display: flex;
		justify-content: space-between;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rm-grid {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 2px;
		background: var(--terminal-bg-panel-sunken);
		touch-action: none;
	}
	.rm-grid:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.rm-row {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 2px;
	}

	.rm-cell {
		display: flex;
		align-items: center;
		justify-content: center;
		aspect-ratio: 1 / 1;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-tertiary);
		font-family: inherit;
		font-size: var(--terminal-text-14);
		cursor: grab;
		transition:
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.rm-cell:active {
		cursor: grabbing;
	}
	.rm-cell--origin {
		border-color: var(--terminal-fg-secondary);
	}
	.rm-cell--hover {
		border-color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-raised);
	}
	.rm-cell--sim {
		border-color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-accent-amber);
	}
	.rm-cell:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -1px;
	}

	.rm-pin {
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-14);
		line-height: 1;
	}

	.rm-labels {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.rm-label--stress-lo { grid-column: 1; }
	.rm-label--stress-hi { grid-column: 2; text-align: right; }
	.rm-label--growth-lo { grid-column: 1; }
	.rm-label--growth-hi { grid-column: 2; text-align: right; }

	.rm-footer {
		display: flex;
		justify-content: flex-end;
	}
	.rm-sim-coords {
		font-size: var(--terminal-text-11);
		color: var(--terminal-accent-amber);
		letter-spacing: var(--terminal-tracking-caps);
		font-variant-numeric: tabular-nums;
	}
</style>
