<!--
	TerminalStatusBar.svelte — bottom chrome strip.
	==============================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell + layer taxonomy, Appendix C tokens.

	Fixed 28px bottom strip for the terminal shell. Three-zone grid:
		• Left   — NETZ brand, build SHA, environment (dev/staging
		           hidden on prod), org name, user initials.
		• Center — optional `ticker` snippet slot (TerminalShell
		           injects AlertTicker output here). STANDBY fallback
		           when omitted.
		• Right  — connection LiveDot (pulse animation, color-coded
		           by stream state), UTC clock (tabular-nums, 1Hz
		           tick via $effect + setInterval with cleanup).

	Pure presentational primitive — build SHA, org name, user initials,
	and connection status are passed in as props. TerminalShell resolves
	these from import.meta.env + Clerk context + TerminalStream
	aggregation.

	Z-index var(--terminal-z-statusbar) = 30, above page content (10)
	and rail (20), below modals (50), focus mode (60), and palette (70).
-->
<script lang="ts">
	import type { Snippet } from "svelte";
	import { formatMonoTime } from "@investintell/ui";

	export type TerminalStatusBarConnectionStatus =
		| "connecting"
		| "open"
		| "degraded"
		| "closed"
		| "error";

	interface TerminalStatusBarProps {
		/**
		 * Build SHA string (7-char short form). Resolved via
		 * `import.meta.env.VITE_BUILD_SHA` by TerminalShell. Empty
		 * string or "local" is acceptable during dev bootstrap.
		 */
		buildSha: string;
		/**
		 * Environment label. Rendered for "dev" and "staging" only —
		 * suppressed on "prod" to reduce visual noise on the
		 * institutional surface.
		 */
		environment: "dev" | "staging" | "prod";
		/**
		 * Organization name (from Clerk org context). Empty string
		 * allowed during bootstrap; bar shows an em-dash fallback.
		 */
		orgName: string;
		/**
		 * Current user initials (2 char mono). Empty string fallback.
		 */
		userInitials: string;
		/**
		 * Optional ticker content — a snippet provided by
		 * TerminalShell that injects AlertTicker output. When omitted,
		 * the ticker zone shows a subtle STANDBY placeholder.
		 */
		ticker?: Snippet;
		/**
		 * Connection status driving the LiveDot color. Parent
		 * (TerminalShell) aggregates the state of all active
		 * TerminalStream subscriptions and hands down the worst
		 * status.
		 */
		connectionStatus: TerminalStatusBarConnectionStatus;
	}

	let {
		buildSha,
		environment,
		orgName,
		userInitials,
		ticker,
		connectionStatus,
	}: TerminalStatusBarProps = $props();

	let utcClock = $state("--:--:-- UTC");

	// 1Hz UTC clock via the mono formatter from @investintell/ui. The
	// formatter is tabular-safe (zero-padded HH:MM:SS) and locale-
	// independent. `$effect` cleanup guarantees the interval stops
	// when the shell unmounts.
	$effect(() => {
		if (typeof window === "undefined") return;
		const tick = () => {
			utcClock = formatMonoTime(new Date(), "utc");
		};
		tick();
		const interval = window.setInterval(tick, 1000);
		return () => {
			window.clearInterval(interval);
		};
	});

	const showEnvironmentBadge = $derived(
		environment === "dev" || environment === "staging",
	);

	const displayBuildSha = $derived(buildSha.length > 0 ? buildSha : "local");
	const displayOrgName = $derived(orgName.length > 0 ? orgName : "—");
	const displayUserInitials = $derived(
		userInitials.length > 0 ? userInitials : "—",
	);

	const connectionLabel = $derived(connectionStatusLabel(connectionStatus));

	function connectionStatusLabel(
		status: TerminalStatusBarConnectionStatus,
	): string {
		switch (status) {
			case "open":
				return "LIVE";
			case "connecting":
				return "LINK";
			case "degraded":
				return "DEGR";
			case "closed":
				return "DOWN";
			case "error":
				return "ERR";
		}
	}
</script>

<footer class="sb-bar" aria-label="Terminal status bar">
	<div class="sb-cluster sb-cluster--left">
		<span class="sb-brand">[ NETZ ]</span>
		<span class="sb-sep">//</span>
		<span class="sb-meta">
			<span class="sb-meta-label">BUILD</span>
			<span class="sb-meta-value">{displayBuildSha}</span>
		</span>
		{#if showEnvironmentBadge}
			<span class="sb-sep">//</span>
			<span class="sb-env sb-env--{environment}">{environment.toUpperCase()}</span>
		{/if}
		<span class="sb-sep">//</span>
		<span class="sb-meta">
			<span class="sb-meta-label">ORG</span>
			<span class="sb-meta-value">{displayOrgName}</span>
		</span>
		<span class="sb-sep">//</span>
		<span class="sb-meta">
			<span class="sb-meta-label">USR</span>
			<span class="sb-meta-value">{displayUserInitials}</span>
		</span>
	</div>

	<div class="sb-cluster sb-cluster--center">
		{#if ticker}
			{@render ticker()}
		{:else}
			<span class="sb-standby">STANDBY</span>
		{/if}
	</div>

	<div class="sb-cluster sb-cluster--right">
		<span class="sb-conn sb-conn--{connectionStatus}">
			<span class="sb-dot"></span>
			<span class="sb-conn-label">{connectionLabel}</span>
		</span>
		<span class="sb-sep">//</span>
		<span class="sb-clock">{utcClock}</span>
	</div>
</footer>

<style>
	.sb-bar {
		position: relative;
		z-index: var(--terminal-z-statusbar);
		display: grid;
		grid-template-columns: auto 1fr auto;
		align-items: center;
		gap: var(--terminal-space-4);
		height: 28px;
		padding: 0 var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		border-top: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		box-sizing: border-box;
	}

	.sb-cluster {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		min-width: 0;
	}

	.sb-cluster--center {
		justify-content: center;
		overflow: hidden;
		white-space: nowrap;
	}

	.sb-cluster--right {
		justify-content: flex-end;
	}

	.sb-brand {
		color: var(--terminal-fg-primary);
		font-weight: 700;
	}

	.sb-sep {
		color: var(--terminal-fg-muted);
	}

	.sb-meta {
		display: inline-flex;
		align-items: baseline;
		gap: 4px;
	}

	.sb-meta-label {
		color: var(--terminal-fg-tertiary);
	}

	.sb-meta-value {
		color: var(--terminal-fg-secondary);
		font-variant-numeric: tabular-nums;
	}

	.sb-env {
		padding: 1px var(--terminal-space-1);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-primary);
	}

	.sb-env--dev {
		border-color: var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
	}

	.sb-env--staging {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.sb-standby {
		color: var(--terminal-fg-muted);
		font-variant-numeric: tabular-nums;
		animation: sb-pulse 2.4s ease-in-out infinite;
	}

	.sb-conn {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		color: var(--terminal-fg-secondary);
	}

	.sb-dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		background: var(--terminal-status-neutral);
		animation: sb-pulse 1.8s ease-in-out infinite;
	}

	.sb-conn--open .sb-dot {
		background: var(--terminal-status-success);
		box-shadow: 0 0 8px var(--terminal-status-success);
	}

	.sb-conn--open .sb-conn-label {
		color: var(--terminal-status-success);
	}

	.sb-conn--connecting .sb-dot {
		background: var(--terminal-accent-cyan);
		box-shadow: 0 0 8px var(--terminal-accent-cyan);
	}

	.sb-conn--connecting .sb-conn-label {
		color: var(--terminal-accent-cyan);
	}

	.sb-conn--degraded .sb-dot {
		background: var(--terminal-status-warn);
		box-shadow: 0 0 8px var(--terminal-status-warn);
	}

	.sb-conn--degraded .sb-conn-label {
		color: var(--terminal-status-warn);
	}

	.sb-conn--closed .sb-dot,
	.sb-conn--error .sb-dot {
		background: var(--terminal-status-error);
		box-shadow: 0 0 8px var(--terminal-status-error);
	}

	.sb-conn--closed .sb-conn-label,
	.sb-conn--error .sb-conn-label {
		color: var(--terminal-status-error);
	}

	.sb-clock {
		color: var(--terminal-fg-secondary);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.04em;
	}

	@keyframes sb-pulse {
		0%,
		100% {
			opacity: 0.45;
		}
		50% {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.sb-dot,
		.sb-standby {
			animation: none;
		}
	}
</style>
