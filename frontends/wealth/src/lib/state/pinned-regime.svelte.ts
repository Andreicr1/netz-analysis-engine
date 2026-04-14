/**
 * Shared reactive state for pinned regime.
 *
 * Written by macro desk [PIN REGIME] button, read by
 * TerminalContextRail and any downstream surface that
 * needs regime context (Builder, Screener, etc.).
 *
 * Module-level $state — singleton across the app.
 * No localStorage (terminal namespace forbids it).
 */

export interface PinnedRegime {
	label: string;
	region: string;
	score: number;
}

let current = $state<PinnedRegime | null>(null);

export const pinnedRegime = {
	get current() {
		return current;
	},
	pin(regime: PinnedRegime) {
		current = regime;
	},
	clear() {
		current = null;
	},
};
