<!--
  PortfolioSubNav — Phase 5 Task 5.5 of the portfolio-enterprise-workbench
  plan. Three-pill ribbon mounted under the global TopNav by every
  /portfolio/* route.

  DL1 — Three-phase URL contract:
    Builder    → /portfolio
    Analytics  → /portfolio/analytics  (Phase 6 will rebuild this)
    Live       → /portfolio/live       (Phase 8 will create this)

  Each pill carries a derived badge from the workspace store:
    - drafts_in_progress           — count of portfolios in state='draft'
    - subjects_under_analysis      — Phase 6 will populate from BottomTabDock
    - live_portfolios_with_open_alerts — Phase 7 will populate

  Phase 5 ships zero-default badges where the data isn't computed yet
  (Phase 6/7/9 will fill them in). The badges are stable shape so future
  phases can drop in real numbers without touching this component.
-->
<script lang="ts">
	import { page } from "$app/stores";

	interface Pill {
		key: "builder" | "analytics" | "live";
		href: string;
		label: string;
		badge: number;
	}

	interface Props {
		/** Optional badge counts; defaults to zero so Phase 5 ships clean. */
		draftsInProgress?: number;
		subjectsUnderAnalysis?: number;
		liveAlertsCount?: number;
	}

	let {
		draftsInProgress = 0,
		subjectsUnderAnalysis = 0,
		liveAlertsCount = 0,
	}: Props = $props();

	const pills = $derived<Pill[]>([
		{
			key: "builder",
			href: "/portfolio",
			label: "Builder",
			badge: draftsInProgress,
		},
		{
			key: "analytics",
			href: "/portfolio/analytics",
			label: "Analytics",
			badge: subjectsUnderAnalysis,
		},
		{
			key: "live",
			href: "/portfolio/live",
			label: "Live",
			badge: liveAlertsCount,
		},
	]);

	// DL1 — the active pill is derived from the URL pathname, never
	// from a local store. /portfolio is the default Builder route.
	const activeKey = $derived.by(() => {
		const path = $page.url.pathname;
		if (path.startsWith("/portfolio/live")) return "live";
		if (path.startsWith("/portfolio/analytics")) return "analytics";
		return "builder";
	});
</script>

<nav class="psn-root" aria-label="Portfolio sub-navigation">
	{#each pills as pill (pill.key)}
		{@const isActive = activeKey === pill.key}
		<a
			href={pill.href}
			class="psn-pill"
			class:psn-pill--active={isActive}
			data-sveltekit-noscroll
			aria-current={isActive ? "page" : undefined}
		>
			<span class="psn-label">{pill.label}</span>
			{#if pill.badge > 0}
				<span class="psn-badge">{pill.badge}</span>
			{/if}
		</a>
	{/each}
</nav>

<style>
	.psn-root {
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.psn-pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 22px;
		border: 1px solid #ffffff;
		border-radius: 36px;
		background: #000000;
		color: #ffffff;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		text-decoration: none;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease;
	}

	.psn-pill:hover {
		background: #1a1b20;
	}

	.psn-pill--active {
		background: #0177fb;
		border-color: transparent;
	}

	.psn-pill--active:hover {
		background: #0166d9;
	}

	.psn-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 6px;
		background: rgba(255, 255, 255, 0.18);
		border-radius: 999px;
		font-size: 10px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: #ffffff;
	}

	.psn-pill--active .psn-badge {
		background: rgba(255, 255, 255, 0.24);
	}
</style>
