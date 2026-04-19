<!--
  Screener — Terminal OS high-density asset screening surface.

  Filter state is owned by the URL. Changing a filter calls goto() to
  update searchParams; the Shell reacts to the new prop values and
  re-fetches. This makes the screener reload-safe and deep-linkable.

  Row clicks dispatch a "focustrigger" CustomEvent (via the use:focusTrigger
  action on each <tr>). This page listens for the bubbled event and mounts
  FundFocusMode. ESC or backdrop click dismisses FocusMode.
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import TerminalScreenerShell from "$wealth/components/screener/terminal/TerminalScreenerShell.svelte";
	import FundFocusMode from "$wealth/components/terminal/focus-mode/fund/FundFocusMode.svelte";
	import type { FocusTriggerOptions } from "$wealth/components/terminal/focus-mode/focus-trigger";
	import { DEFAULT_FILTERS, type FilterState } from "$wealth/components/screener/terminal/TerminalScreenerFilters.svelte";

	// ── URL → FilterState ─────���─────────────────────────
	function parseFiltersFromURL(params: URLSearchParams): FilterState {
		const universeRaw = params.get("universe");
		const strategyRaw = params.get("strategy");
		const geoRaw = params.get("geography");

		const managerRaw = params.get("manager");

		return {
			fundUniverse: universeRaw ? new Set(universeRaw.split(",")) : new Set(),
			strategies: strategyRaw ? new Set(strategyRaw.split(",")) : new Set(),
			geographies: geoRaw ? new Set(geoRaw.split(",")) : new Set(),
			aumMin: Number(params.get("aum_min") ?? 0),
			aumMax: Number(params.get("aum_max") ?? 0),
			returnMin: Number(params.get("min_return") ?? -999),
			returnMax: Number(params.get("max_return") ?? 999),
			expenseMax: Number(params.get("max_expense") ?? 10),
			eliteOnly: params.get("elite") === "1",
			managerNames: managerRaw ? managerRaw.split(",") : [],
			sharpeMin: params.get("sharpe_min") ?? "",
			sharpeMax: params.get("sharpe_max") ?? "",
			drawdownMinPct: params.get("dd_min") ?? "",
			drawdownMaxPct: params.get("dd_max") ?? "",
			volatilityMax: params.get("vol_max") ?? "",
			return10yMin: params.get("ret_10y_min") ?? "",
			return10yMax: params.get("ret_10y_max") ?? "",
		};
	}

	const currentFilters = $derived(parseFiltersFromURL(page.url.searchParams));

	// ── FilterState → URL ───────────────────────────────
	function handleFiltersChange(next: FilterState) {
		const url = new URL(page.url);
		const p = url.searchParams;

		// Clear all filter params first, then set non-default values
		// Clear all filter params
		for (const k of ["universe", "strategy", "geography", "aum_min", "aum_max", "min_return", "max_return", "max_expense", "elite", "manager", "sharpe_min", "sharpe_max", "dd_min", "dd_max", "vol_max", "ret_10y_min", "ret_10y_max"]) {
			p.delete(k);
		}

		if (next.fundUniverse.size > 0) p.set("universe", [...next.fundUniverse].join(","));
		if (next.strategies.size > 0) p.set("strategy", [...next.strategies].join(","));
		if (next.geographies.size > 0) p.set("geography", [...next.geographies].join(","));
		if (next.aumMin > 0) p.set("aum_min", String(Math.round(next.aumMin)));
		if (next.aumMax > 0) p.set("aum_max", String(Math.round(next.aumMax)));
		if (next.returnMin > -999) p.set("min_return", String(next.returnMin));
		if (next.returnMax < 999) p.set("max_return", String(next.returnMax));
		if (next.expenseMax < 10) p.set("max_expense", String(next.expenseMax));
		if (next.eliteOnly) p.set("elite", "1");
		if (next.managerNames.length > 0) p.set("manager", next.managerNames.join(","));
		if (next.sharpeMin) p.set("sharpe_min", next.sharpeMin);
		if (next.sharpeMax) p.set("sharpe_max", next.sharpeMax);
		if (next.drawdownMinPct) p.set("dd_min", next.drawdownMinPct);
		if (next.drawdownMaxPct) p.set("dd_max", next.drawdownMaxPct);
		if (next.volatilityMax) p.set("vol_max", next.volatilityMax);
		if (next.return10yMin) p.set("ret_10y_min", next.return10yMin);
		if (next.return10yMax) p.set("ret_10y_max", next.return10yMax);

		const qs = p.toString();
		const target = url.pathname + (qs ? "?" + qs : "");
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- url.pathname is already a current-route path; appending a query string is equivalent to url.toString().
		goto(target, { replaceState: true, noScroll: true, keepFocus: true });
	}

	// ── FocusMode ───────────────────────────────────────
	let focusEntity = $state<FocusTriggerOptions | null>(null);
	let containerEl: HTMLDivElement | undefined = $state();

	$effect(() => {
		if (!containerEl) return;
		const handler = (event: Event) => {
			const detail = (event as CustomEvent<FocusTriggerOptions>).detail;
			focusEntity = detail;
		};
		containerEl.addEventListener("focustrigger", handler);
		return () => containerEl?.removeEventListener("focustrigger", handler);
	});

	function closeFocusMode() {
		focusEntity = null;
	}
</script>

<div bind:this={containerEl} data-screener-root class="screener-page-root">
	<TerminalScreenerShell filters={currentFilters} onFiltersChange={handleFiltersChange} />
</div>

{#if focusEntity}
	<FundFocusMode
		fundId={focusEntity.entityId}
		fundLabel={focusEntity.entityLabel ?? ""}
		onClose={closeFocusMode}
	/>
{/if}

<style>
	.screener-page-root {
		height: 100%;
		overflow: hidden;
	}

	/*
	 * Override LayoutCage padding for the screener surface.
	 * Data-dense grids need every pixel — 8px vs the 24px default.
	 * The :global targets the cage wrapper rendered by TerminalShell.
	 */
	:global(.lc-cage--standard:has([data-screener-root])) {
		padding: var(--terminal-space-2) !important;
	}
</style>
