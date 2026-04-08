<!--
  Fund Detail layout — second-level tab strip for a single fund.

  Nested inside `/screener/+layout.svelte` (which renders the global
  Screening | Analytics pills and the Run Review action). This layout
  adds a fund-scoped tab row underneath:

      [ Fact Sheet ]  [ Risk Analysis ]

  Each child route renders its own full header + content inside the
  shared scroll container. No data is loaded here — the child pages
  continue to own their `+page.server.ts` loads, so the layout stays
  stateless and cheap.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import type { Snippet } from "svelte";

	let { children }: { children: Snippet } = $props();

	const fundId = $derived($page.params.id ?? "");

	type FundTab = "factsheet" | "analysis";

	const activeTab = $derived.by<FundTab>(() => {
		const path = $page.url.pathname;
		if (path.endsWith("/analysis") || path.includes("/analysis?")) {
			return "analysis";
		}
		return "factsheet";
	});

	const TABS: readonly { key: FundTab; href: (id: string) => string; label: string }[] = [
		{
			key: "factsheet",
			href: (id) => `/screener/fund/${id}`,
			label: "Fact Sheet",
		},
		{
			key: "analysis",
			href: (id) => `/screener/fund/${id}/analysis`,
			label: "Risk Analysis",
		},
	];
</script>

<div class="fl-root">
	<nav class="fl-tabs" aria-label="Fund detail sections">
		{#each TABS as tab (tab.key)}
			<a
				href={tab.href(fundId)}
				class="fl-tab"
				class:fl-tab--active={activeTab === tab.key}
				data-sveltekit-noscroll
			>
				{tab.label}
			</a>
		{/each}
	</nav>

	<div class="fl-slot">
		{@render children()}
	</div>
</div>

<style>
	.fl-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		gap: 16px;
	}

	.fl-tabs {
		display: inline-flex;
		gap: 4px;
		flex-shrink: 0;
		padding: 0;
	}

	.fl-tab {
		display: inline-flex;
		align-items: center;
		padding: 8px 18px;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: uppercase;
		color: #9ca3af;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 999px;
		text-decoration: none;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
	}

	.fl-tab:hover {
		color: #f3f4f6;
		border-color: rgba(255, 255, 255, 0.24);
		background: rgba(255, 255, 255, 0.03);
	}

	.fl-tab--active {
		background: #0177fb;
		color: #ffffff;
		border-color: transparent;
	}

	.fl-tab--active:hover {
		background: #0166d9;
		color: #ffffff;
	}

	.fl-slot {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		border-radius: 16px;
		background: var(--ii-bg);
	}

	/* Custom scrollbar to match the rest of the screener shell. */
	.fl-slot::-webkit-scrollbar {
		width: 8px;
	}
	.fl-slot::-webkit-scrollbar-track {
		background: transparent;
	}
	.fl-slot::-webkit-scrollbar-thumb {
		background: #2a2b33;
		border-radius: 4px;
	}
	.fl-slot::-webkit-scrollbar-thumb:hover {
		background: #3f3f46;
	}
</style>
