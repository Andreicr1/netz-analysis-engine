/**
 * Page-scoped macro regime simulation store.
 *
 * Deliberately isolated under `lib/components/terminal/macro/` (NOT
 * `$wealth/state/*`) per plan §M5 so that importing it from anywhere
 * else in the app is visibly wrong in code review — the simulation
 * must never leak into `pinnedRegime` (which is the global TopNav
 * indicator) or into any backend call.
 *
 * Zero persistence. Zero network. In-memory `$state` only. Reload
 * resets the matrix to "no simulation."
 */

export interface RegimeCell {
	/** 0-indexed row (stress axis). */
	row: number;
	/** 0-indexed column (growth axis). */
	col: number;
}

export interface MacroSimulationStore {
	readonly cell: RegimeCell | null;
	readonly label: string | null;
	setCell(next: RegimeCell | null): void;
	reset(): void;
}

/**
 * Canonical 4x4 regime grid labels.
 *
 * Rows (top → bottom) climb in stress: LOW_STRESS, NORMAL, ELEVATED,
 * CRISIS. Cols (left → right) traverse growth: CONTRACTION, SLOWDOWN,
 * EXPANSION, OVERHEAT. The intersection is the simulated regime.
 *
 * Labels are derived, never authored — UI reads from here to avoid
 * drift between the pin label on the Hero and the tooltip on the
 * matrix cell.
 */
export const STRESS_LABELS = [
	"LOW_STRESS",
	"NORMAL",
	"ELEVATED",
	"CRISIS",
] as const;

export const GROWTH_LABELS = [
	"CONTRACTION",
	"SLOWDOWN",
	"EXPANSION",
	"OVERHEAT",
] as const;

export function labelFor(cell: RegimeCell): string {
	const stress = STRESS_LABELS[cell.row] ?? "UNKNOWN";
	const growth = GROWTH_LABELS[cell.col] ?? "UNKNOWN";
	return `${stress} · ${growth}`;
}

export function createMacroSimulationStore(): MacroSimulationStore {
	let cell = $state<RegimeCell | null>(null);

	const label = $derived(cell ? labelFor(cell) : null);

	return {
		get cell() {
			return cell;
		},
		get label() {
			return label;
		},
		setCell(next: RegimeCell | null) {
			cell = next;
		},
		reset() {
			cell = null;
		},
	};
}
