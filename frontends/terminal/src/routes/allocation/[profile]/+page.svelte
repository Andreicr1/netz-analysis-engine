<!--
  X3.1 Builder Workspace.

  Fused surface replacing the former /allocation/[profile] (IPS
  governance only) + /portfolio/builder (optimizer workspace). One
  page, one cage, three tabs:

    [ STRATEGIC | PORTFOLIO | STRESS ]

  Layout (top to bottom):
    BuilderBreadcrumb         Screener > Macro > Builder > {PROFILE}
    ProfileStrip              Conservative / Moderate / Growth (+CVaR)
    RegimeContextStrip        Global regime bands, persistent across tabs
    BuilderTabStrip           The three top-level tabs
    <tab content panel>       StrategicTabContent / PortfolioTabContent /
                              StressTabContent

  URL state:
    pathname  → profile         (/allocation/{conservative|moderate|growth})
    ?tab=     → active tab      (strategic | portfolio | stress)
    ?portfolio_id= → (PORTFOLIO / STRESS tabs) preselects a portfolio;
                     otherwise the workspace auto-selects portfolios[0]

  Tab strip + profile strip use replaceState so back-button returns
  to the previous workspace state rather than unwinding each click.

  LayoutCage override preserved via data-allocation-root so the page
  keeps the dense 8px padding mirroring the screener (feedback_
  layout_cage_pattern.md). The cage provides calc(100vh - 88px);
  inside we run a flex-column so the tab panel gets min-height: 0
  for correct scroll containment inside the PORTFOLIO 40/60 grid.
-->
<script lang="ts">
	import "@investintell/ui/styles/surfaces/builder";
	import { getContext } from "svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { page } from "$app/state";
	import { createClientApiClient } from "$wealth/api/client";
	import type { AllocationProfile } from "$wealth/types/allocation-page";

	import BuilderBreadcrumb from "../../../lib/components/builder/BuilderBreadcrumb.svelte";
	import ProfileStrip from "../../../lib/components/builder/ProfileStrip.svelte";
	import BuilderTabStrip, {
		type BuilderTab,
	} from "../../../lib/components/builder/BuilderTabStrip.svelte";
	import StrategicTabContent from "../../../lib/components/builder/StrategicTabContent.svelte";
	import PortfolioTabContent from "../../../lib/components/builder/PortfolioTabContent.svelte";
	import StressTabContent from "../../../lib/components/builder/StressTabContent.svelte";
	import RegimeContextStrip from "$wealth/components/allocation/RegimeContextStrip.svelte";

	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const strategic = $derived(data.strategic.data);
	const strategicErr = $derived(data.strategic.error);
	const profile = $derived(data.profile as AllocationProfile | null);

	// Active top-level tab, parsed defensively from ?tab= with a
	// strategic default. Anything unrecognized silently reverts.
	const activeTab = $derived<BuilderTab>(
		parseTab(page.url.searchParams.get("tab")),
	);

	function parseTab(raw: string | null): BuilderTab {
		if (raw === "portfolio" || raw === "stress") return raw;
		return "strategic";
	}

	function setTab(tab: BuilderTab) {
		const url = new URL(page.url);
		if (tab === "strategic") url.searchParams.delete("tab");
		else url.searchParams.set("tab", tab);
		goto(url.pathname + url.search, {
			replaceState: true,
			noScroll: true,
			keepFocus: true,
		});
	}

	function setProfile(p: AllocationProfile) {
		const url = new URL(page.url);
		url.pathname = `/allocation/${p}`;
		goto(url.pathname + url.search, { keepFocus: true });
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const apiBase =
		import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	function clientApi() {
		return createClientApiClient(getToken);
	}
	async function apiGet<T>(path: string): Promise<T> {
		return clientApi().get<T>(path);
	}
	async function apiPost<T>(path: string, body?: unknown): Promise<T> {
		return clientApi().post<T>(path, body ?? {});
	}

	async function refresh(): Promise<void> {
		await invalidateAll();
	}

	// CVaR-by-profile map powering the ProfileStrip subtitles.
	// Only the active profile is loaded in `strategic` — the other
	// two appear as "CVaR —" until switched to. This is cheap and
	// avoids a fan-out of three strategic-allocation fetches on
	// every load.
	const cvarByProfile = $derived<
		Partial<Record<AllocationProfile, number | null>>
	>(
		profile && strategic
			? { [profile]: strategic.cvar_limit }
			: {},
	);

	// Resolve the selected portfolio's display name for the breadcrumb
	// badge — only relevant on PORTFOLIO / STRESS tabs where a portfolio
	// is actually in play.
	const selectedPortfolioName = $derived.by(() => {
		if (activeTab === "strategic") return null;
		const id = page.url.searchParams.get("portfolio_id");
		if (!id) return null;
		return data.portfolios.find((p) => p.id === id)?.display_name ?? null;
	});
</script>

<div data-allocation-root data-surface="builder" class="workspace">
	{#if !profile || strategicErr || !strategic}
		<div class="workspace__error">
			<h2 class="workspace__error-title">Unable to load allocation</h2>
			<p class="workspace__error-body">
				{strategicErr?.message ?? "Unknown error."}
			</p>
		</div>
	{:else}
		<BuilderBreadcrumb {profile} portfolioName={selectedPortfolioName} />

		<ProfileStrip
			current={profile}
			{cvarByProfile}
			onchange={setProfile}
		/>

		<RegimeContextStrip data={data.regime} />

		<BuilderTabStrip active={activeTab} onchange={setTab} />

		<div class="workspace__panel">
			{#if activeTab === "strategic"}
				<div class="workspace__panel-scroll">
					<StrategicTabContent
						{profile}
						{strategic}
						proposal={data.proposal}
						history={data.history}
						{refresh}
						{apiGet}
						{apiPost}
						{getToken}
						{apiBase}
					/>
				</div>
			{:else if activeTab === "portfolio"}
				<PortfolioTabContent portfolios={data.portfolios} />
			{:else if activeTab === "stress"}
				<StressTabContent portfolios={data.portfolios} />
			{/if}
		</div>
	{/if}
</div>

<style>
	.workspace {
		height: 100%;
		display: flex;
		flex-direction: column;
		min-height: 0;
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
		background: var(--terminal-bg-void);
	}

	/*
	 * Override LayoutCage padding for the builder workspace. The
	 * screener pattern — 8px instead of the 24px default — keeps the
	 * strip stack and the PORTFOLIO 40/60 grid on one screen without
	 * sacrificing the black-margin cage height.
	 */
	:global(.lc-cage--standard:has([data-allocation-root])) {
		padding: var(--terminal-space-2) !important;
	}

	.workspace__panel {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	/*
	 * STRATEGIC owns its own scroll — it's a long page with multiple
	 * stacked sections. PORTFOLIO / STRESS manage their own shells
	 * and must not double-scroll.
	 */
	.workspace__panel-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: var(--terminal-space-3);
	}

	.workspace__error {
		border: var(--terminal-border-alert);
		background: var(--terminal-bg-panel);
		padding: var(--terminal-space-4);
		margin: var(--terminal-space-4);
	}
	.workspace__error-title {
		font-size: var(--terminal-text-12);
		margin: 0;
		color: var(--terminal-status-error);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.workspace__error-body {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		margin: var(--terminal-space-1) 0 0;
	}
</style>
