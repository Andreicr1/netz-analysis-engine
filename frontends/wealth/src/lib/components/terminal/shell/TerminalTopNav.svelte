<!--
	TerminalTopNav.svelte — global navigation chrome.
	=================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell, Appendix B navigation flow, Appendix C tokens.

	Fixed 32px top chrome strip. Renders the full master plan navigation
	vision — 8 tabs, 3 active routes and 5 pending (Phase 4–7). Pending
	tabs are visibly rendered (greyed, PENDING badge, title attribute
	with phase attribution) so the institutional surface shows the
	complete product scope from day one. No "coming soon" hidden tabs.

	Right cluster: Cmd/Ctrl+K palette trigger (platform-detected, SSR-
	safe), REGIME placeholder for Phase 7 regime stream, tenant switcher
	button (stubbed pending Clerk SDK resolution), alert pill with
	count badge, session chip with user initials.

	This component has no keyboard handling of its own. Global shortcuts
	(Cmd+K, rail [ / ], g-prefix go-to) live inside TerminalShell's
	window keydown listener.
-->
<script lang="ts">
	import { resolve } from "$app/paths";

	// Resolved hrefs for active routes. The lint rule
	// `svelte/no-navigation-without-resolve` rejects any href that is
	// not the direct return value of a plain Identifier argument to
	// `resolve(...)`; hardcoding the three active route literals is
	// the only pattern its AST matcher accepts.
	const HREF_SCREENER = resolve("/terminal-screener");
	const HREF_LIVE = resolve("/portfolio/live");
	const HREF_RESEARCH = resolve("/research");

	type TabStatus = "active" | "pending";

	interface PrimaryTab {
		id: string;
		label: string;
		href: string;
		status: TabStatus;
		pendingReason?: string;
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
		 * User initials rendered inside the session chip. Two-char mono
		 * expected; empty string fallback renders "—".
		 */
		userInitials: string;
		/**
		 * Organization name shown on the tenant switcher placeholder.
		 * Empty string fallback renders "NETZ".
		 */
		orgName: string;
	}

	let {
		activePath,
		onOpenPalette,
		alertCount = 0,
		userInitials,
		orgName,
	}: TerminalTopNavProps = $props();

	const PRIMARY_TABS: ReadonlyArray<PrimaryTab> = [
		{ id: "macro",    label: "MACRO",    href: "/macro",             status: "pending", pendingReason: "Phase 7 — Macro Desk" },
		{ id: "alloc",    label: "ALLOC",    href: "/allocation",        status: "pending", pendingReason: "Phase 7 — Allocation" },
		{ id: "screener", label: "SCREENER", href: HREF_SCREENER,        status: "active" },
		{ id: "builder",  label: "BUILDER",  href: "/portfolio/build",   status: "pending", pendingReason: "Phase 4 — Portfolio Builder" },
		{ id: "live",     label: "LIVE",     href: HREF_LIVE,            status: "active" },
		{ id: "research", label: "RESEARCH", href: HREF_RESEARCH,        status: "active" },
		{ id: "alerts",   label: "ALERTS",   href: "/alerts",            status: "pending", pendingReason: "Phase 5 — Alerts Inbox" },
		{ id: "dd",       label: "DD",       href: "/dd",                status: "pending", pendingReason: "Phase 6 — DD Queue" },
	];

	function isHrefActive(href: string): boolean {
		return (
			href === HREF_SCREENER ||
			href === HREF_LIVE ||
			href === HREF_RESEARCH
		);
	}

	function activePathSegment(href: string): string {
		if (href === HREF_SCREENER) return "/terminal-screener";
		if (href === HREF_LIVE) return "/portfolio/live";
		if (href === HREF_RESEARCH) return "/research";
		return href;
	}

	function isActiveTab(tab: PrimaryTab): boolean {
		if (tab.status !== "active") return false;
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
	const displayOrgName = $derived(orgName.length > 0 ? orgName : "NETZ");

	const alertBadgeLabel = $derived(
		alertCount > 99 ? "99+" : String(alertCount),
	);

	function handleTenantClick() {
		// Pending Clerk SDK resolution — no-op for Part C. Phase 2+
		// wires the real org switcher when the SvelteKit SDK
		// stabilizes (see CLAUDE.md §Clerk SvelteKit SDK Note).
	}

	function handleAlertClick() {
		// Alerts route is pending (Phase 5). Intentional no-op — the
		// ticker hover state in CSS surfaces the pending state.
	}

	function handleSessionClick() {
		// Clerk user menu — pending SDK. Same rationale as tenant
		// switcher. No-op for Part C.
	}
</script>

<nav class="tn-nav" aria-label="Terminal primary navigation">
	<div class="tn-brand">
		<span class="tn-brand-mark">▣</span>
		<span class="tn-brand-name">NETZ / TERMINAL</span>
	</div>

	<ul class="tn-tabs" role="list">
		{#each PRIMARY_TABS as tab (tab.id)}
			<li class="tn-tab-item">
				{#if tab.id === "screener"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_SCREENER}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else if tab.id === "live"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_LIVE}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else if tab.id === "research"}
					<a
						class="tn-tab tn-tab--active"
						class:tn-tab--current={isActiveTab(tab)}
						href={HREF_RESEARCH}
						data-sveltekit-preload-data="hover"
					>
						<span class="tn-tab-label">{tab.label}</span>
					</a>
				{:else}
					<span
						class="tn-tab tn-tab--pending"
						role="link"
						aria-disabled="true"
						title={tab.pendingReason ?? "Pending"}
					>
						<span class="tn-tab-label">{tab.label}</span>
						<span class="tn-tab-pending-badge">PENDING</span>
					</span>
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
			<span class="tn-regime-value">STANDBY</span>
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
			title={alertCount > 0 ? `${alertCount} unread` : "Alerts inbox — Phase 5 pending"}
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

	.tn-tab--pending {
		color: var(--terminal-fg-muted);
		cursor: not-allowed;
	}

	.tn-tab-label {
		font-weight: 600;
	}

	.tn-tab-pending-badge {
		display: inline-block;
		padding: 1px 4px;
		font-size: var(--terminal-text-10);
		letter-spacing: 0.08em;
		color: var(--terminal-fg-tertiary);
		border: 1px solid var(--terminal-fg-muted);
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
</style>
