<!--
	TerminalTopNav.svelte — global navigation chrome.
	=================================================

	Source of truth: docs/plans/2026-04-19-ii-terminal-extraction.md
		§X2 route move — institutional flow rewire.

	F-key ordering (X2): six canonical tabs in institutional-lifecycle
	order, Macro context flowing into Builder allocation flowing into
	DD validation. No RESEARCH tab at top-level — research is scoped
	under SCREENER (/screener/research).

		F1  LIVE      /live
		F2  SCREENER  /screener
		F3  MACRO     /macro
		F4  BUILDER   /allocation  (builder surface = allocation review)
		F5  DD        /dd
		F6  ALERTS    /alerts

	Fixed 32px top chrome strip.

	Shared across wealth and terminal during X2–X6. Wealth adds minimal
	redirect shims for /live and /screener/research so the resolve()
	typecheck passes in both apps: see
	frontends/wealth/src/routes/(terminal)/live (redirects to
	/portfolio/live) and frontends/wealth/src/routes/(app)/screener/
	research (redirects to /research). The /screener F-key resolves to
	wealth's existing (app)/screener page — legacy wealth-app screener —
	during transition; canonical /screener lives on the terminal app.

	This component has no keyboard handling of its own. Global shortcuts
	(Cmd+K, rail [ / ], g-prefix go-to) live inside TerminalShell's
	window keydown listener.
-->
<script lang="ts">
	import { resolve } from "$app/paths";
	import { goto } from "$app/navigation";
	import { getContext, onDestroy } from "svelte";
	import { createClientApiClient } from "$wealth/api/client";

	// Resolved hrefs for the 6 F-key tabs. The lint rule
	// `svelte/no-navigation-without-resolve` rejects any href that is
	// not the direct return value of a plain Identifier argument to
	// `resolve(...)`; hardcoding one identifier per route is the only
	// pattern its AST matcher accepts.
	const HREF_LIVE = resolve("/live");
	const HREF_SCREENER = resolve("/screener");
	const HREF_MACRO = resolve("/macro");
	const HREF_BUILDER = resolve("/allocation");
	const HREF_DD = resolve("/dd");
	const HREF_ALERTS = resolve("/alerts");

	interface PrimaryTab {
		id: string;
		label: string;
		href: string;
		fKey: number;
	}

	interface TerminalTopNavProps {
		/**
		 * Currently active pathname (from `$page.url.pathname`).
		 * TopNav uses this to highlight the active tab.
		 */
		activePath: string;
		/**
		 * Callback fired when user clicks the command palette trigger.
		 * TerminalShell wires this to toggle the CommandPalette overlay.
		 */
		onOpenPalette: () => void;
		/**
		 * Optional: unread alert count driving the alert pill badge.
		 * Zero means no badge; non-zero renders a red circle with count.
		 */
		alertCount?: number;
		/**
		 * DD queue count (pending + in_progress). Drives a badge on
		 * the DD tab when > 0.
		 */
		ddQueueCount?: number;
		/**
		 * User initials rendered inside the session chip. Two-char mono
		 * expected; empty string fallback renders "—".
		 */
		userInitials: string;
		/**
		 * Organization name shown on the tenant switcher placeholder.
		 * Empty string fallback renders "II" (InvestIntell product
		 * default for unauthenticated / pre-hydration chrome).
		 */
		orgName: string;
	}

	let {
		activePath,
		onOpenPalette,
		alertCount = 0,
		ddQueueCount = 0,
		userInitials,
		orgName,
	}: TerminalTopNavProps = $props();

	// ─── Live regime from /allocation/regime ───────────────────
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const regimeApi = createClientApiClient(getToken);

	interface GlobalRegimeRead {
		regime: string;
		confidence: number;
		as_of_date: string | null;
	}

	let regimeLabel = $state("STANDBY");
	let regimeLoaded = $state(false);

	const REGIME_DISPLAY: Record<string, string> = {
		REGIME_NORMAL: "Normal",
		normal: "Normal",
		REGIME_RISK_ON: "Risk On",
		risk_on: "Risk On",
		REGIME_RISK_OFF: "Risk Off",
		risk_off: "Risk Off",
		REGIME_CRISIS: "Crisis",
		crisis: "Crisis",
	};

	function sanitizeRegime(raw: string): string {
		return REGIME_DISPLAY[raw] ?? raw;
	}

	const regimeColorClass = $derived.by(() => {
		switch (regimeLabel) {
			case "Normal": return "tn-regime-value--ok";
			case "Risk On": return "tn-regime-value--cyan";
			case "Risk Off": return "tn-regime-value--amber";
			case "Crisis": return "tn-regime-value--error";
			default: return "";
		}
	});

	async function fetchRegime() {
		try {
			const res = await regimeApi.get<GlobalRegimeRead>("/allocation/regime");
			regimeLabel = sanitizeRegime(res.regime);
			regimeLoaded = true;
		} catch {
			// Keep current label on failure
		}
	}

	$effect(() => {
		fetchRegime();
		const timer = setInterval(fetchRegime, 5 * 60 * 1000);
		return () => clearInterval(timer);
	});

	const PRIMARY_TABS: ReadonlyArray<PrimaryTab> = [
		{ id: "live",     label: "LIVE",     href: HREF_LIVE,     fKey: 1 },
		{ id: "screener", label: "SCREENER", href: HREF_SCREENER, fKey: 2 },
		{ id: "macro",    label: "MACRO",    href: HREF_MACRO,    fKey: 3 },
		{ id: "builder",  label: "BUILDER",  href: HREF_BUILDER,  fKey: 4 },
		{ id: "dd",       label: "DD",       href: HREF_DD,       fKey: 5 },
		{ id: "alerts",   label: "ALERTS",   href: HREF_ALERTS,   fKey: 6 },
	];

	function isHrefActive(href: string): boolean {
		return (
			href === HREF_LIVE ||
			href === HREF_SCREENER ||
			href === HREF_MACRO ||
			href === HREF_BUILDER ||
			href === HREF_DD ||
			href === HREF_ALERTS
		);
	}

	function activePathSegment(href: string): string {
		if (href === HREF_LIVE) return "/live";
		if (href === HREF_SCREENER) return "/screener";
		if (href === HREF_MACRO) return "/macro";
		if (href === HREF_BUILDER) return "/allocation";
		if (href === HREF_DD) return "/dd";
		if (href === HREF_ALERTS) return "/alerts";
		return href;
	}

	function isActiveTab(tab: PrimaryTab): boolean {
		if (!isHrefActive(tab.href)) return false;
		return activePath.startsWith(activePathSegment(tab.href));
	}

	// Platform detection for the Cmd+K affordance. SSR-safe default to
	// Ctrl, hydrate to Cmd on macOS when navigator becomes available.
	let paletteHint = $state("Ctrl+K");
	$effect(() => {
		if (typeof navigator === "undefined") return;
		const platform = navigator.platform ?? "";
		const userAgent = navigator.userAgent ?? "";
		const isMac = /Mac|iPhone|iPad|iPod/.test(platform) || /Mac OS X/.test(userAgent);
		paletteHint = isMac ? "⌘K" : "Ctrl+K";
	});

	const displayUserInitials = $derived(
		userInitials.length > 0 ? userInitials : "—",
	);
	const displayOrgName = $derived(orgName.length > 0 ? orgName : "II");

	const alertBadgeLabel = $derived(
		alertCount > 99 ? "99+" : String(alertCount),
	);

	function handleTenantClick() {
		// Pending Clerk SDK resolution — no-op for X2. A later sprint
		// wires the real org switcher when the SvelteKit SDK stabilizes
		// (see CLAUDE.md §Clerk SvelteKit SDK Note).
	}

	function handleAlertClick() {
		// Navigate to the alerts inbox route.
		goto(HREF_ALERTS);
	}

	function handleSessionClick() {
		// Clerk user menu — pending SDK. Same rationale as tenant
		// switcher. No-op for X2.
	}
</script>

<nav class="tn-nav" aria-label="Terminal primary navigation">
	<div class="tn-brand">
		<span class="tn-brand-mark">▣</span>
		<span class="tn-brand-name">{displayOrgName} / TERMINAL</span>
	</div>

	<ul class="tn-tabs" role="list">
		{#each PRIMARY_TABS as tab (tab.id)}
			<li class="tn-tab-item">
				{#if tab.id === "live"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_LIVE}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-fkey">F{tab.fKey}</span>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else if tab.id === "screener"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_SCREENER}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-fkey">F{tab.fKey}</span>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else if tab.id === "macro"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_MACRO}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-fkey">F{tab.fKey}</span>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else if tab.id === "builder"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_BUILDER}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-fkey">F{tab.fKey}</span>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else if tab.id === "dd"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_DD}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-fkey">F{tab.fKey}</span>
						<span class="tn-tab-label">{tab.label}</span>
						{#if ddQueueCount > 0}
							<span class="tn-dd-badge">{ddQueueCount > 99 ? "99+" : ddQueueCount}</span>
						{/if}
					</a>
				{:else if tab.id === "alerts"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_ALERTS}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-fkey">F{tab.fKey}</span>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{/if}
			</li>
		{/each}
	</ul>

	<div class="tn-right">
		<button
			type="button"
			class="tn-palette-trigger"
			onclick={onOpenPalette}
			aria-label="Open command palette"
		>
			<span class="tn-palette-bracket">[</span>
			<span class="tn-palette-hint">{paletteHint}</span>
			<span class="tn-palette-bracket">]</span>
		</button>

		<span class="tn-regime" aria-live="polite">
			<span class="tn-regime-label">REGIME</span>
			<span class="tn-regime-value {regimeColorClass}">{regimeLabel}</span>
		</span>

		<button
			type="button"
			class="tn-tenant"
			onclick={handleTenantClick}
			title="Tenant switcher pending Clerk SDK"
			aria-label={`Current organization ${displayOrgName}`}
		>
			<span class="tn-tenant-label">{displayOrgName}</span>
			<span class="tn-tenant-caret">▾</span>
		</button>

		<button
			type="button"
			class="tn-alerts"
			onclick={handleAlertClick}
			aria-label={alertCount > 0 ? `${alertCount} unread alerts` : "Alerts inbox"}
			title={alertCount > 0 ? `${alertCount} unread` : "Alerts inbox"}
		>
			<span class="tn-alerts-icon">△</span>
			{#if alertCount > 0}
				<span class="tn-alerts-badge">{alertBadgeLabel}</span>
			{/if}
		</button>

		<button
			type="button"
			class="tn-session"
			onclick={handleSessionClick}
			aria-label="User session menu"
			title="User menu pending Clerk SDK"
		>
			{displayUserInitials}
		</button>
	</div>
</nav>

<style>
	.tn-nav {
		position: relative;
		z-index: var(--terminal-z-panel);
		display: grid;
		grid-template-columns: auto 1fr auto;
		align-items: stretch;
		gap: var(--terminal-space-4);
		height: 32px;
		padding: 0 var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		box-sizing: border-box;
	}

	.tn-brand {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding-right: var(--terminal-space-4);
		border-right: var(--terminal-border-hairline);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-primary);
		font-weight: 700;
	}

	.tn-brand-mark {
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-12);
	}

	.tn-brand-name {
		font-size: var(--terminal-text-10);
		letter-spacing: 0.12em;
	}

	.tn-tabs {
		display: flex;
		align-items: stretch;
		margin: 0;
		padding: 0;
		list-style: none;
		gap: 0;
		min-width: 0;
	}

	.tn-tab-item {
		display: flex;
		align-items: stretch;
	}

	.tn-tab {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: 0 var(--terminal-space-3);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		text-decoration: none;
		color: var(--terminal-fg-tertiary);
		border-bottom: 2px solid transparent;
		transition:
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
		user-select: none;
	}

	.tn-tab--active {
		cursor: pointer;
	}

	.tn-tab--active:hover {
		color: var(--terminal-accent-amber);
	}

	.tn-tab--current {
		color: var(--terminal-accent-amber);
		border-bottom-color: var(--terminal-accent-amber);
	}

	.tn-tab--active:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.tn-tab-fkey {
		font-weight: 500;
		color: var(--terminal-fg-muted);
		letter-spacing: 0;
	}

	.tn-tab-label {
		font-weight: 600;
	}

	.tn-right {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding-left: var(--terminal-space-4);
		border-left: var(--terminal-border-hairline);
	}

	.tn-palette-trigger {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		padding: 2px var(--terminal-space-2);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		cursor: pointer;
		text-transform: uppercase;
		transition:
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.tn-palette-trigger:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.tn-palette-trigger:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.tn-palette-bracket {
		color: var(--terminal-fg-muted);
	}

	.tn-palette-hint {
		font-weight: 600;
	}

	.tn-regime {
		display: inline-flex;
		align-items: baseline;
		gap: var(--terminal-space-1);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
	}

	.tn-regime-label {
		color: var(--terminal-fg-tertiary);
	}

	.tn-regime-value {
		font-weight: 600;
	}

	.tn-regime-value--ok {
		color: var(--terminal-status-ok);
	}

	.tn-regime-value--cyan {
		color: var(--terminal-accent-cyan);
	}

	.tn-regime-value--amber {
		color: var(--terminal-accent-amber);
	}

	.tn-regime-value--error {
		color: var(--terminal-status-error);
	}

	.tn-tenant {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		padding: 2px var(--terminal-space-2);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		cursor: pointer;
		text-transform: uppercase;
		transition: border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.tn-tenant:hover {
		border-color: var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
	}

	.tn-tenant:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.tn-tenant-caret {
		color: var(--terminal-fg-muted);
	}

	.tn-alerts {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-12);
		cursor: pointer;
		transition:
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.tn-alerts:hover {
		border-color: var(--terminal-status-warn);
		color: var(--terminal-status-warn);
	}

	.tn-alerts:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.tn-alerts-badge {
		position: absolute;
		top: -6px;
		right: -8px;
		min-width: 14px;
		height: 14px;
		padding: 0 3px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: var(--terminal-status-error);
		color: var(--terminal-fg-inverted);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0;
		box-sizing: border-box;
	}

	.tn-session {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: 0;
		cursor: pointer;
		text-transform: uppercase;
		font-weight: 700;
		transition: border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.tn-session:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.tn-session:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.tn-dd-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 14px;
		height: 14px;
		padding: 0 3px;
		background: var(--terminal-accent-cyan);
		color: var(--terminal-fg-inverted);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0;
		box-sizing: border-box;
	}
</style>
