<!--
  /portfolio/analytics — Phase 6 Block A rebuild.

  Replaces the legacy 4-sub-tab analytics page with the canonical
  AnalysisGrid + ScopeSwitcher + BottomTabDock framework. Block A
  ships placeholder cells; Block B fills the grid with real
  ECharts components.

  All state is URL-driven (DL15 — no localStorage):
    ?scope=model_portfolios|approved_universe|compare_both
    ?group=returns_risk|holdings|peer|stress
    ?subject=<id>
    #tabs=<base64url(JSON)>

  Per the Discovery analysis route precedent, every URL mutation goes
  through ``goto({replaceState: true, noScroll: true, keepFocus: true})``
  so filter interaction does not push history entries — Back returns
  the PM to the page they came from, not three filter steps ago.
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import PortfolioAnalyticsShell from "$lib/components/portfolio/PortfolioAnalyticsShell.svelte";
	import {
		parseScopeParam,
		parseGroupParam,
		tabFingerprint,
		type AnalyticsScope,
		type AnalyticsGroupFocus,
		type AnalyticsSubject,
		type AnalyticsTab,
	} from "$lib/portfolio/analytics-types";
	import {
		decodeAnalyticsHash,
		encodeAnalyticsHash,
		applyTabOp,
	} from "$lib/portfolio/analytics-hash";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { ApprovedUniverseFund } from "./+page.server";

	let { data }: { data: PageData } = $props();

	const portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);
	const approvedFunds = $derived((data.approvedFunds ?? []) as ApprovedUniverseFund[]);

	// ── URL-derived state (no workspace mutations) ─────────────
	const scope = $derived<AnalyticsScope>(
		parseScopeParam(page.url.searchParams.get("scope")),
	);
	const group = $derived<AnalyticsGroupFocus>(
		parseGroupParam(page.url.searchParams.get("group")),
	);
	const subjectId = $derived<string | null>(
		page.url.searchParams.get("subject"),
	);

	// ── BottomTabDock state from URL hash ───────────────────────
	// Derived from $page.url.hash. The reactive $derived re-runs on
	// every URL change so deep links and back/forward navigation
	// always project the right tab list.
	const hashState = $derived(decodeAnalyticsHash(page.url.hash));
	const tabs = $derived(hashState.tabs);
	const activeTabId = $derived(hashState.activeId);

	// ── Subject lists per scope ────────────────────────────────
	// Both lists are mapped to the canonical AnalyticsSubject shape so
	// the FilterRail subject list does not branch on scope.
	const subjectsByScope = $derived.by<Record<AnalyticsScope, AnalyticsSubject[]>>(
		() => {
			const portfolioSubjects: AnalyticsSubject[] = portfolios.map((p) => ({
				id: p.id,
				name: p.display_name,
				subtitle: p.profile,
				badge: p.state,
				scope: "model_portfolios",
			}));
			const fundSubjects: AnalyticsSubject[] = approvedFunds.map((f) => ({
				id: f.instrument_id,
				name: f.name,
				subtitle: [f.ticker, f.strategy_label].filter(Boolean).join(" · ") || undefined,
				scope: "approved_universe",
			}));
			return {
				model_portfolios: portfolioSubjects,
				approved_universe: fundSubjects,
				// Compare Both is locked to v1.1 — empty list returns
				// the v1.1 placeholder via buildGridSpec().
				compare_both: [],
			};
		},
	);

	const subjects = $derived(subjectsByScope[scope]);

	// ── URL mutation helpers ───────────────────────────────────

	async function patchQuery(updates: Record<string, string | null>) {
		const url = new URL(page.url);
		for (const [k, v] of Object.entries(updates)) {
			if (v === null) {
				url.searchParams.delete(k);
			} else {
				url.searchParams.set(k, v);
			}
		}
		await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	async function patchHash(nextTabs: AnalyticsTab[], nextActiveId: string | null) {
		const url = new URL(page.url);
		const fragment = encodeAnalyticsHash({
			v: 1,
			tabs: nextTabs,
			activeId: nextActiveId,
		});
		url.hash = fragment ? `#${fragment}` : "";
		await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	// ── Event handlers ─────────────────────────────────────────

	function handleScopeChange(next: AnalyticsScope) {
		// Switching scope clears the selected subject (the previous
		// id may not exist in the new list). The first subject in the
		// new list is auto-selected if present.
		const list = subjectsByScope[next];
		const firstId = list[0]?.id ?? null;
		void patchQuery({
			scope: next,
			subject: firstId,
		});
	}

	function handleGroupChange(next: AnalyticsGroupFocus) {
		void patchQuery({ group: next });
	}

	function handleSelectSubject(subject: AnalyticsSubject) {
		// Open or update a tab with this subject's fingerprint and
		// promote it to active. The hash codec dedupes by id.
		const id = tabFingerprint(subject.scope, subject.id);
		const newTab: AnalyticsTab = {
			id,
			subjectId: subject.id,
			scope: subject.scope,
			label: subject.name,
			subtitle: subject.subtitle,
			groupFocus: group,
		};
		const result = applyTabOp(tabs, { kind: "open", tab: newTab });
		// Update the URL: subject query + hash both flip in one goto.
		const url = new URL(page.url);
		url.searchParams.set("subject", subject.id);
		const fragment = encodeAnalyticsHash({
			v: 1,
			tabs: result.tabs,
			activeId: result.activeId,
		});
		url.hash = fragment ? `#${fragment}` : "";
		void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	function handleSelectTab(tab: AnalyticsTab) {
		const result = applyTabOp(tabs, { kind: "select", id: tab.id });
		const url = new URL(page.url);
		url.searchParams.set("scope", tab.scope);
		url.searchParams.set("subject", tab.subjectId);
		url.searchParams.set("group", tab.groupFocus);
		const fragment = encodeAnalyticsHash({
			v: 1,
			tabs: result.tabs,
			activeId: result.activeId,
		});
		url.hash = fragment ? `#${fragment}` : "";
		void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	function handleCloseTab(tab: AnalyticsTab) {
		const result = applyTabOp(tabs, { kind: "close", id: tab.id });
		void patchHash(result.tabs, result.activeId);
	}
</script>

<svelte:head>
	<title>Portfolio Analytics — InvestIntell</title>
</svelte:head>

<PortfolioAnalyticsShell
	{scope}
	{group}
	{subjects}
	selectedSubjectId={subjectId}
	{tabs}
	{activeTabId}
	onScopeChange={handleScopeChange}
	onGroupChange={handleGroupChange}
	onSelectSubject={handleSelectSubject}
	onSelectTab={handleSelectTab}
	onCloseTab={handleCloseTab}
/>
