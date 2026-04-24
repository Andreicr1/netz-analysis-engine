function cssVar(name: string, fallback: string): string {
	if (typeof window === "undefined") return fallback;
	const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	return value || fallback;
}

export function terminalChartTokens() {
	return {
		bg: cssVar("--terminal-bg-panel", "#0d1333"),
		panel: cssVar("--terminal-bg-panel-raised", "#111a42"),
		grid: cssVar("--terminal-fg-disabled", "#22305c"),
		text: cssVar("--terminal-fg-primary", "#f6f7fb"),
		muted: cssVar("--terminal-fg-muted", "#7b89b8"),
		secondary: cssVar("--terminal-fg-secondary", "#b6c4f4"),
		cyan: cssVar("--terminal-accent-cyan", "#38f2c2"),
		cyanDim: cssVar("--terminal-accent-cyan-dim", "#2ccca7"),
		amber: cssVar("--terminal-accent-amber", "#ffa35a"),
		violet: cssVar("--terminal-accent-violet", "#9a86ff"),
		error: cssVar("--terminal-status-error", "#ff6d8f"),
		success: cssVar("--terminal-status-success", "#37e39e"),
		font: cssVar("--terminal-font-mono", "IBM Plex Mono, monospace"),
	};
}

export type TerminalChartTokens = ReturnType<typeof terminalChartTokens>;
