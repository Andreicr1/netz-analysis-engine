<!--
  GlobalAlertInbox — Phase 7 Alerts Unification bell icon dropdown.

  Renders as the notification bell in the top nav (replacing the
  Phase 0 dead stub at +layout.svelte:256). Clicking the bell opens
  a right-anchored dropdown listing the most recent unified alerts;
  clicking a row acknowledges it and navigates to ``alert.href``.

  Architecture:
    - Global component mounted ONCE in the (app)/+layout.svelte so
      it is visible on every wealth route.
    - Owns its open/closed dropdown state locally (click-outside
      closes); subscribes to workspace.alertsInbox for the data.
    - On mount, fires ``workspace.startAlertsPolling()`` at 60s
      cadence; on destroy, clears the interval via
      ``workspace.stopAlertsPolling()``.
    - Frontend never branches on alert.source per the Phase 7 user
      mandate. Only severity and title/subtitle drive rendering.

  Per CLAUDE.md:
    - DL15: zero localStorage. Acknowledge state is purely a backend
      write via workspace.acknowledgeAlert.
    - DL16: every timestamp goes through @investintell/ui formatters.
    - OD-26: strict empty state when there are no alerts.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { onMount, onDestroy, getContext } from "svelte";
	import Bell from "lucide-svelte/icons/bell";
	import Check from "lucide-svelte/icons/check";
	import Circle from "lucide-svelte/icons/circle";
	import { EmptyState, formatDateTime } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import type {
		UnifiedAlert,
		UnifiedSeverity,
	} from "$lib/types/alerts";

	// Inject the JWT getter on mount so the workspace polling works
	// even if no other wealth component has hydrated yet.
	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let open = $state(false);
	let rootEl: HTMLDivElement | undefined = $state();

	// ── Reactive slices from the workspace store ─────────────
	const inbox = $derived(workspace.alertsInbox);
	const isLoading = $derived(workspace.isLoadingAlerts);
	const error = $derived(workspace.alertsError);
	const items = $derived(inbox?.items ?? []);
	const unreadCount = $derived(inbox?.unread_count ?? 0);

	// ── Polling lifecycle ───────────────────────────────────
	onMount(() => {
		workspace.setGetToken(getToken);
		workspace.startAlertsPolling(60_000);

		const handleClickOutside = (event: MouseEvent) => {
			if (!rootEl) return;
			if (!rootEl.contains(event.target as Node)) open = false;
		};
		const handleEscape = (event: KeyboardEvent) => {
			if (event.key === "Escape") open = false;
		};
		document.addEventListener("mousedown", handleClickOutside);
		document.addEventListener("keydown", handleEscape);
		return () => {
			document.removeEventListener("mousedown", handleClickOutside);
			document.removeEventListener("keydown", handleEscape);
		};
	});

	onDestroy(() => {
		workspace.stopAlertsPolling();
	});

	// ── Handlers ─────────────────────────────────────────────
	function toggle() {
		open = !open;
	}

	async function handleItemClick(alert: UnifiedAlert) {
		// Acknowledge first, then navigate — the acknowledge writes
		// to the backend which refreshes the inbox via the store.
		// Per DL15 the read state lives on the server, not in
		// localStorage.
		if (alert.acknowledged_at === null) {
			void workspace.acknowledgeAlert(alert.source, alert.id);
		}
		if (alert.href) {
			open = false;
			void goto(alert.href);
		}
	}

	// ── Severity dot color (pure presentation) ──────────────
	function severityAccent(severity: UnifiedSeverity): "info" | "warning" | "danger" {
		switch (severity) {
			case "critical":
				return "danger";
			case "warning":
				return "warning";
			case "info":
			default:
				return "info";
		}
	}

	const countLabel = $derived(unreadCount > 99 ? "99+" : String(unreadCount));
</script>

<div class="gai-root" bind:this={rootEl}>
	<button
		type="button"
		class="gai-bell"
		class:gai-bell--active={open}
		onclick={toggle}
		aria-label={unreadCount > 0
			? `${unreadCount} unread alert${unreadCount === 1 ? "" : "s"}`
			: "Notifications"}
		aria-expanded={open}
	>
		<Bell size={18} class="gai-bell-icon" />
		{#if unreadCount > 0}
			<span class="gai-badge" data-size={unreadCount > 9 ? "wide" : "narrow"}>
				{countLabel}
			</span>
		{/if}
	</button>

	{#if open}
		<div class="gai-dropdown" role="dialog" aria-label="Alerts inbox">
			<header class="gai-header">
				<span class="gai-header-title">Alerts</span>
				{#if unreadCount > 0}
					<span class="gai-header-count">{unreadCount} unread</span>
				{:else}
					<span class="gai-header-count gai-header-count--muted">All caught up</span>
				{/if}
			</header>

			<div class="gai-body">
				{#if isLoading && items.length === 0}
					<div class="gai-state">
						<EmptyState title="Loading alerts…" message="Fetching the unified inbox." />
					</div>
				{:else if error && items.length === 0}
					<div class="gai-state">
						<EmptyState title="Could not load alerts" message={error} />
					</div>
				{:else if items.length === 0}
					<div class="gai-state">
						<EmptyState
							title="No open alerts"
							message="Drift detection, portfolio monitoring, and live price staleness checks are all quiet."
						/>
					</div>
				{:else}
					<ul class="gai-list" role="list">
						{#each items as alert (alert.id + alert.source)}
							{@const accent = severityAccent(alert.severity)}
							{@const isUnread = alert.acknowledged_at === null}
							<li class="gai-item-wrap">
								<button
									type="button"
									class="gai-item"
									class:gai-item--unread={isUnread}
									onclick={() => handleItemClick(alert)}
								>
									<span class="gai-severity-dot" data-accent={accent} aria-hidden="true"></span>
									<span class="gai-item-body">
										<span class="gai-item-title">{alert.title}</span>
										{#if alert.subtitle}
											<span class="gai-item-subtitle">{alert.subtitle}</span>
										{/if}
										<span class="gai-item-meta">
											{formatDateTime(alert.created_at)}
										</span>
									</span>
									{#if isUnread}
										<span class="gai-unread-marker" aria-label="Unread">
											<Circle size={8} fill="currentColor" />
										</span>
									{:else}
										<span class="gai-read-marker" aria-label="Read">
											<Check size={12} />
										</span>
									{/if}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.gai-root {
		position: relative;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	/* ── Bell button (replaces Phase 0 stub) ───────────────── */
	.gai-bell {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 10px;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 9999px;
		background: var(--ii-surface-elevated, #141519);
		color: var(--ii-text-primary, #ffffff);
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease;
	}
	.gai-bell:hover {
		background: var(--ii-surface-raised, #1a1b20);
	}
	.gai-bell--active {
		background: var(--ii-surface-raised, #1a1b20);
		border-color: var(--ii-primary, #0177fb);
	}
	:global(.gai-bell-icon) {
		color: var(--ii-text-primary, #ffffff);
	}

	.gai-badge {
		position: absolute;
		top: -2px;
		right: -2px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 16px;
		height: 16px;
		padding: 0 5px;
		font-size: 9px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: #ffffff;
		background: var(--ii-danger, #fc1a1a);
		border: 2px solid var(--ii-surface-elevated, #141519);
		border-radius: 9999px;
		pointer-events: none;
	}
	.gai-badge[data-size="wide"] {
		padding: 0 6px;
	}

	/* ── Dropdown panel ─────────────────────────────────────── */
	.gai-dropdown {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		width: 380px;
		max-height: 480px;
		background: var(--ii-surface-panel, #141519);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 12px;
		box-shadow: 0 24px 48px rgba(0, 0, 0, 0.4);
		z-index: 200;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.gai-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.gai-header-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.gai-header-count {
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-primary, #0177fb);
	}
	.gai-header-count--muted {
		color: var(--ii-text-muted, #85a0bd);
	}

	.gai-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.gai-state {
		padding: 24px 16px;
	}

	/* ── List rows ──────────────────────────────────────────── */
	.gai-list {
		list-style: none;
		margin: 0;
		padding: 4px 0;
	}

	.gai-item-wrap {
		padding: 0 4px;
	}

	.gai-item {
		display: grid;
		grid-template-columns: 12px 1fr auto;
		grid-template-rows: auto;
		align-items: flex-start;
		gap: 10px;
		width: 100%;
		padding: 10px 12px;
		background: transparent;
		border: 1px solid transparent;
		border-radius: 8px;
		text-align: left;
		cursor: pointer;
		font-family: inherit;
		transition: background 120ms ease, border-color 120ms ease;
	}
	.gai-item:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.gai-item--unread {
		background: rgba(1, 119, 251, 0.05);
	}
	.gai-item--unread:hover {
		background: rgba(1, 119, 251, 0.1);
	}

	.gai-severity-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-top: 5px;
	}
	.gai-severity-dot[data-accent="info"] {
		background: var(--ii-primary, #0177fb);
	}
	.gai-severity-dot[data-accent="warning"] {
		background: var(--ii-warning, #f0a020);
	}
	.gai-severity-dot[data-accent="danger"] {
		background: var(--ii-danger, #fc1a1a);
	}

	.gai-item-body {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.gai-item-title {
		font-size: 13px;
		font-weight: 600;
		color: var(--ii-text-primary, #ffffff);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.gai-item-subtitle {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.gai-item-meta {
		font-size: 10px;
		color: var(--ii-text-muted, #85a0bd);
		font-variant-numeric: tabular-nums;
		margin-top: 2px;
	}

	.gai-unread-marker {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		color: var(--ii-primary, #0177fb);
		flex-shrink: 0;
	}
	.gai-read-marker {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		color: var(--ii-text-muted, #85a0bd);
		opacity: 0.5;
		flex-shrink: 0;
	}
</style>
