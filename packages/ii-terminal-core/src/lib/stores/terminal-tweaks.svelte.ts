/**
 * Terminal runtime tweaks — density / accent / theme.
 *
 * In-memory only. No localStorage, no URL param. Resets on
 * hard reload (confirmed trade-off per plan scope-decision #3:
 * docs/plans/2026-04-18-netz-terminal-parity.md §0).
 *
 * Usage:
 *   const tweaks = createTerminalTweaks();
 *   setContext(TERMINAL_TWEAKS_KEY, tweaks);
 *   ...
 *   const tweaks = getContext<TerminalTweaks>(TERMINAL_TWEAKS_KEY);
 *
 * The TerminalShell binds `data-density`, `data-accent`, `data-theme`
 * onto its root element so the @investintell/ui tokens shipped in
 * PR-1 activate via attribute selectors.
 */

import type { Accent, Density, TerminalTheme } from "../components/terminal/primitives";

export const TERMINAL_TWEAKS_KEY = Symbol("netz:terminal-tweaks");

export interface TerminalTweaks {
	readonly density: Density;
	readonly accent: Accent;
	readonly theme: TerminalTheme;
	setDensity(v: Density): void;
	setAccent(v: Accent): void;
	setTheme(v: TerminalTheme): void;
}

export function createTerminalTweaks(): TerminalTweaks {
	let density = $state<Density>("standard");
	let accent = $state<Accent>("amber");
	let theme = $state<TerminalTheme>("dark");
	return {
		get density() {
			return density;
		},
		get accent() {
			return accent;
		},
		get theme() {
			return theme;
		},
		setDensity(v) {
			density = v;
		},
		setAccent(v) {
			accent = v;
		},
		setTheme(v) {
			theme = v;
		},
	};
}
