<!--
  SeriesPicker — indicator catalog with search, region/frequency chips, favorites, hard cap 8.
  Spec: WM-S1-02
-->
<script lang="ts">
	import { slide } from "svelte/transition";
	import { createDebouncedState } from "$wealth/utils/reactivity";

	export interface IndicatorEntry {
		id: string;
		name: string;
		group: string;
		frequency: "D" | "M" | "Q" | "A";
		source: "treasury" | "ofr" | "bis" | "imf" | "fred";
		region?: string;
		unit?: string;
		params?: Record<string, string>;
	}

	interface Props {
		selected: Set<string>;
		favorites?: Set<string>;
		onToggle: (id: string) => void;
		onToggleFavorite?: (id: string) => void;
	}

	let {
		selected,
		favorites = new Set<string>(),
		onToggle,
		onToggleFavorite,
	}: Props = $props();

	const searchState = createDebouncedState("", 250);
	let regionFilter = $state("All");
	let frequencyFilter = $state("All");
	let sourceFilter = $state<"All" | "fred" | "treasury" | "ofr" | "bis" | "imf">("All");
	// All groups expanded by default — collapsing-everything-on-mount made
	// the picker look empty on first render, which audit flagged as broken UX.
	// Initial set is computed lazily once the CATALOG is in scope below.
	let expandedGroups = $state<Set<string>>(new Set());

	const REGIONS = ["All", "US", "Europe", "Asia", "EM", "Global"] as const;
	const FREQUENCIES = ["All", "D", "M", "Q", "A"] as const;
	const SOURCES = ["All", "fred", "treasury", "ofr", "bis", "imf"] as const;
	const SOURCE_LABELS: Record<string, string> = {
		All: "All",
		fred: "FRED",
		treasury: "Treasury",
		ofr: "OFR",
		bis: "BIS",
		imf: "IMF",
	};
	const MAX_SERIES = 8;
	const WARN_THRESHOLD = 6;
	const FAVORITES_GROUP = "★ Favorites";

	const FREQ_LABELS: Record<string, string> = { D: "Daily", M: "Monthly", Q: "Quarterly", A: "Annual" };

	const CATALOG: IndicatorEntry[] = [
		// ── FRED: US Activity ──
		{ id: "fred:VIXCLS", name: "VIX", group: "FRED US Activity", frequency: "D", source: "fred", region: "US", unit: "idx", params: { series_id: "VIXCLS" } },
		{ id: "fred:UNRATE", name: "Unemployment Rate", group: "FRED US Activity", frequency: "M", source: "fred", region: "US", unit: "%", params: { series_id: "UNRATE" } },
		{ id: "fred:PAYEMS", name: "Nonfarm Payrolls", group: "FRED US Activity", frequency: "M", source: "fred", region: "US", unit: "K", params: { series_id: "PAYEMS" } },
		{ id: "fred:INDPRO", name: "Industrial Production", group: "FRED US Activity", frequency: "M", source: "fred", region: "US", unit: "idx", params: { series_id: "INDPRO" } },
		{ id: "fred:UMCSENT", name: "Consumer Sentiment (Michigan)", group: "FRED US Activity", frequency: "M", source: "fred", region: "US", unit: "idx", params: { series_id: "UMCSENT" } },
		{ id: "fred:JTSJOL", name: "JOLTS Openings", group: "FRED US Activity", frequency: "M", source: "fred", region: "US", unit: "K", params: { series_id: "JTSJOL" } },
		{ id: "fred:SAHMREALTIME", name: "Sahm Rule Indicator", group: "FRED US Activity", frequency: "M", source: "fred", region: "US", unit: "pp", params: { series_id: "SAHMREALTIME" } },

		// ── FRED: US Inflation ──
		{ id: "fred:CPI_YOY", name: "CPI YoY (%)", group: "FRED US Inflation", frequency: "M", source: "fred", region: "US", unit: "%", params: { series_id: "CPI_YOY" } },
		{ id: "fred:CPIAUCSL", name: "CPI Index (All Urban)", group: "FRED US Inflation", frequency: "M", source: "fred", region: "US", unit: "idx", params: { series_id: "CPIAUCSL" } },

		// ── FRED: US Rates & Spreads ──
		{ id: "fred:YIELD_CURVE_10Y2Y", name: "Yield Curve 10Y-2Y", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "YIELD_CURVE_10Y2Y" } },
		{ id: "fred:DGS10", name: "10-Year Treasury", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "DGS10" } },
		{ id: "fred:DGS2", name: "2-Year Treasury", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "DGS2" } },
		{ id: "fred:DGS30", name: "30-Year Treasury", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "DGS30" } },
		{ id: "fred:DFF", name: "Fed Funds Rate", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "DFF" } },
		{ id: "fred:SOFR", name: "SOFR", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "SOFR" } },
		{ id: "fred:BAA10Y", name: "Baa Corporate Spread", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "BAA10Y" } },
		{ id: "fred:BAMLH0A0HYM2", name: "HY OAS Spread", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "BAMLH0A0HYM2" } },
		{ id: "fred:NFCI", name: "Financial Conditions (NFCI)", group: "FRED Rates & Spreads", frequency: "D", source: "fred", region: "US", unit: "idx", params: { series_id: "NFCI" } },

		// ── FRED: US Housing ──
		{ id: "fred:CSUSHPINSA", name: "Case-Shiller National HPI", group: "FRED Housing", frequency: "M", source: "fred", region: "US", unit: "idx", params: { series_id: "CSUSHPINSA" } },
		{ id: "fred:HOUST", name: "Housing Starts", group: "FRED Housing", frequency: "M", source: "fred", region: "US", unit: "K", params: { series_id: "HOUST" } },
		{ id: "fred:PERMIT", name: "Building Permits", group: "FRED Housing", frequency: "M", source: "fred", region: "US", unit: "K", params: { series_id: "PERMIT" } },
		{ id: "fred:MORTGAGE30US", name: "30Y Mortgage Rate", group: "FRED Housing", frequency: "D", source: "fred", region: "US", unit: "%", params: { series_id: "MORTGAGE30US" } },

		// ── FRED: Commodities & Energy ──
		{ id: "fred:DCOILWTICO", name: "WTI Crude Oil", group: "FRED Commodities", frequency: "D", source: "fred", region: "Global", unit: "$/bbl", params: { series_id: "DCOILWTICO" } },
		{ id: "fred:DCOILBRENTEU", name: "Brent Crude Oil", group: "FRED Commodities", frequency: "D", source: "fred", region: "Global", unit: "$/bbl", params: { series_id: "DCOILBRENTEU" } },
		{ id: "fred:DHHNGSP", name: "Henry Hub Nat Gas", group: "FRED Commodities", frequency: "D", source: "fred", region: "Global", unit: "$/MMBtu", params: { series_id: "DHHNGSP" } },
		{ id: "fred:GOLDAMGBD228NLBM", name: "Gold (London PM Fix)", group: "FRED Commodities", frequency: "D", source: "fred", region: "Global", unit: "$/oz", params: { series_id: "GOLDAMGBD228NLBM" } },
		{ id: "fred:PCOPPUSDM", name: "Copper Price", group: "FRED Commodities", frequency: "M", source: "fred", region: "Global", unit: "$/mt", params: { series_id: "PCOPPUSDM" } },

		// ── FRED: Global Risk ──
		{ id: "fred:GPRH", name: "Geopolitical Risk Index", group: "FRED Global Risk", frequency: "M", source: "fred", region: "Global", unit: "idx", params: { series_id: "GPRH" } },
		{ id: "fred:USEPUINDXD", name: "Policy Uncertainty (US)", group: "FRED Global Risk", frequency: "D", source: "fred", region: "US", unit: "idx", params: { series_id: "USEPUINDXD" } },
		{ id: "fred:DTWEXBGS", name: "USD Trade-Weighted Index", group: "FRED Global Risk", frequency: "D", source: "fred", region: "Global", unit: "idx", params: { series_id: "DTWEXBGS" } },

		// ── FRED: Europe ──
		{ id: "fred:ECBDFR", name: "ECB Deposit Rate", group: "FRED Europe", frequency: "D", source: "fred", region: "Europe", unit: "%", params: { series_id: "ECBDFR" } },
		{ id: "fred:IRLTLT01DEM156N", name: "German 10Y Bund", group: "FRED Europe", frequency: "M", source: "fred", region: "Europe", unit: "%", params: { series_id: "IRLTLT01DEM156N" } },
		{ id: "fred:CP0000EZ19M086NEST", name: "Eurozone HICP", group: "FRED Europe", frequency: "M", source: "fred", region: "Europe", unit: "idx", params: { series_id: "CP0000EZ19M086NEST" } },
		{ id: "fred:BAMLHE00EHYIEY", name: "Euro HY Effective Yield", group: "FRED Europe", frequency: "D", source: "fred", region: "Europe", unit: "%", params: { series_id: "BAMLHE00EHYIEY" } },

		// ── FRED: Asia ──
		{ id: "fred:IRLTLT01JPM156N", name: "10Y JGB Yield", group: "FRED Asia", frequency: "M", source: "fred", region: "Asia", unit: "%", params: { series_id: "IRLTLT01JPM156N" } },
		{ id: "fred:JPNCPIALLMINMEI", name: "Japan CPI", group: "FRED Asia", frequency: "M", source: "fred", region: "Asia", unit: "idx", params: { series_id: "JPNCPIALLMINMEI" } },
		{ id: "fred:CHNCPIALLMINMEI", name: "China CPI", group: "FRED Asia", frequency: "M", source: "fred", region: "Asia", unit: "idx", params: { series_id: "CHNCPIALLMINMEI" } },

		// ── FRED: Emerging Markets ──
		{ id: "fred:BRACPIALLMINMEI", name: "Brazil CPI", group: "FRED EM", frequency: "M", source: "fred", region: "EM", unit: "idx", params: { series_id: "BRACPIALLMINMEI" } },
		{ id: "fred:INTDSRBRM193N", name: "Brazil SELIC Rate", group: "FRED EM", frequency: "M", source: "fred", region: "EM", unit: "%", params: { series_id: "INTDSRBRM193N" } },
		{ id: "fred:BAMLEMCBPIOAS", name: "EM Corporate OAS", group: "FRED EM", frequency: "D", source: "fred", region: "EM", unit: "bps", params: { series_id: "BAMLEMCBPIOAS" } },

		// ── US Treasury (legacy, via treasury_data) ──
		{ id: "treasury:YIELD_CURVE", name: "Yield Curve (10Y-2Y)", group: "US Treasury", frequency: "D", source: "treasury", region: "US", unit: "bps", params: { series: "YIELD_CURVE" } },
		{ id: "treasury:10Y_RATE", name: "10-Year Rate", group: "US Treasury", frequency: "D", source: "treasury", region: "US", unit: "%", params: { series: "10Y_RATE" } },
		{ id: "treasury:2Y_RATE", name: "2-Year Rate", group: "US Treasury", frequency: "D", source: "treasury", region: "US", unit: "%", params: { series: "2Y_RATE" } },
		{ id: "treasury:30Y_RATE", name: "30-Year Rate", group: "US Treasury", frequency: "D", source: "treasury", region: "US", unit: "%", params: { series: "30Y_RATE" } },
		{ id: "treasury:FED_FUNDS", name: "Fed Funds Rate", group: "US Treasury", frequency: "D", source: "treasury", region: "US", unit: "%", params: { series: "FED_FUNDS" } },

		// ── OFR Hedge Fund ──
		{ id: "ofr:HF_AUM", name: "Hedge Fund AUM", group: "OFR Hedge Fund", frequency: "Q", source: "ofr", region: "Global", unit: "$B", params: { metric: "HF_AUM" } },
		{ id: "ofr:HF_LEVERAGE", name: "Hedge Fund Leverage", group: "OFR Hedge Fund", frequency: "Q", source: "ofr", region: "Global", unit: "x", params: { metric: "HF_LEVERAGE" } },
		{ id: "ofr:HF_REPO_STRESS", name: "Repo Stress Index", group: "OFR Hedge Fund", frequency: "Q", source: "ofr", region: "Global", unit: "idx", params: { metric: "HF_REPO_STRESS" } },

		// ── BIS US ──
		{ id: "bis:US:CREDIT_GAP", name: "Credit-to-GDP Gap (US)", group: "BIS Credit", frequency: "Q", source: "bis", region: "US", unit: "pp", params: { country: "US", indicator: "CREDIT_GAP" } },
		{ id: "bis:US:DSR", name: "Debt Service Ratio (US)", group: "BIS Credit", frequency: "Q", source: "bis", region: "US", unit: "%", params: { country: "US", indicator: "DSR" } },
		{ id: "bis:US:PROPERTY_PRICES", name: "Property Prices (US)", group: "BIS Credit", frequency: "Q", source: "bis", region: "US", unit: "idx", params: { country: "US", indicator: "PROPERTY_PRICES" } },

		// ── BIS Europe ──
		{ id: "bis:GB:CREDIT_GAP", name: "Credit-to-GDP Gap (UK)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Europe", unit: "pp", params: { country: "GB", indicator: "CREDIT_GAP" } },
		{ id: "bis:DE:CREDIT_GAP", name: "Credit-to-GDP Gap (Germany)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Europe", unit: "pp", params: { country: "DE", indicator: "CREDIT_GAP" } },
		{ id: "bis:GB:DSR", name: "Debt Service Ratio (UK)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Europe", unit: "%", params: { country: "GB", indicator: "DSR" } },
		{ id: "bis:DE:DSR", name: "Debt Service Ratio (Germany)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Europe", unit: "%", params: { country: "DE", indicator: "DSR" } },
		{ id: "bis:GB:PROPERTY_PRICES", name: "Property Prices (UK)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Europe", unit: "idx", params: { country: "GB", indicator: "PROPERTY_PRICES" } },
		{ id: "bis:DE:PROPERTY_PRICES", name: "Property Prices (Germany)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Europe", unit: "idx", params: { country: "DE", indicator: "PROPERTY_PRICES" } },

		// ── BIS Asia ──
		{ id: "bis:JP:CREDIT_GAP", name: "Credit-to-GDP Gap (Japan)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Asia", unit: "pp", params: { country: "JP", indicator: "CREDIT_GAP" } },
		{ id: "bis:JP:DSR", name: "Debt Service Ratio (Japan)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Asia", unit: "%", params: { country: "JP", indicator: "DSR" } },
		{ id: "bis:JP:PROPERTY_PRICES", name: "Property Prices (Japan)", group: "BIS Credit", frequency: "Q", source: "bis", region: "Asia", unit: "idx", params: { country: "JP", indicator: "PROPERTY_PRICES" } },

		// ── BIS EM ──
		{ id: "bis:CN:CREDIT_GAP", name: "Credit-to-GDP Gap (China)", group: "BIS Credit", frequency: "Q", source: "bis", region: "EM", unit: "pp", params: { country: "CN", indicator: "CREDIT_GAP" } },
		{ id: "bis:BR:CREDIT_GAP", name: "Credit-to-GDP Gap (Brazil)", group: "BIS Credit", frequency: "Q", source: "bis", region: "EM", unit: "pp", params: { country: "BR", indicator: "CREDIT_GAP" } },
		{ id: "bis:CN:DSR", name: "Debt Service Ratio (China)", group: "BIS Credit", frequency: "Q", source: "bis", region: "EM", unit: "%", params: { country: "CN", indicator: "DSR" } },
		{ id: "bis:BR:DSR", name: "Debt Service Ratio (Brazil)", group: "BIS Credit", frequency: "Q", source: "bis", region: "EM", unit: "%", params: { country: "BR", indicator: "DSR" } },
		{ id: "bis:CN:PROPERTY_PRICES", name: "Property Prices (China)", group: "BIS Credit", frequency: "Q", source: "bis", region: "EM", unit: "idx", params: { country: "CN", indicator: "PROPERTY_PRICES" } },
		{ id: "bis:BR:PROPERTY_PRICES", name: "Property Prices (Brazil)", group: "BIS Credit", frequency: "Q", source: "bis", region: "EM", unit: "idx", params: { country: "BR", indicator: "PROPERTY_PRICES" } },

		// ── IMF US ──
		{ id: "imf:US:NGDP_RPCH", name: "GDP Growth (US)", group: "IMF Outlook", frequency: "A", source: "imf", region: "US", unit: "%", params: { country: "US", indicator: "NGDP_RPCH" } },
		{ id: "imf:US:PCPIPCH", name: "Inflation (US)", group: "IMF Outlook", frequency: "A", source: "imf", region: "US", unit: "%", params: { country: "US", indicator: "PCPIPCH" } },
		{ id: "imf:US:GGXWDG_NGDP", name: "Fiscal Balance (US)", group: "IMF Outlook", frequency: "A", source: "imf", region: "US", unit: "%GDP", params: { country: "US", indicator: "GGXWDG_NGDP" } },

		// ── IMF Europe ──
		{ id: "imf:GB:NGDP_RPCH", name: "GDP Growth (UK)", group: "IMF Outlook", frequency: "A", source: "imf", region: "Europe", unit: "%", params: { country: "GB", indicator: "NGDP_RPCH" } },
		{ id: "imf:DE:NGDP_RPCH", name: "GDP Growth (Germany)", group: "IMF Outlook", frequency: "A", source: "imf", region: "Europe", unit: "%", params: { country: "DE", indicator: "NGDP_RPCH" } },
		{ id: "imf:GB:PCPIPCH", name: "Inflation (UK)", group: "IMF Outlook", frequency: "A", source: "imf", region: "Europe", unit: "%", params: { country: "GB", indicator: "PCPIPCH" } },
		{ id: "imf:DE:PCPIPCH", name: "Inflation (Germany)", group: "IMF Outlook", frequency: "A", source: "imf", region: "Europe", unit: "%", params: { country: "DE", indicator: "PCPIPCH" } },

		// ── IMF Asia ──
		{ id: "imf:JP:NGDP_RPCH", name: "GDP Growth (Japan)", group: "IMF Outlook", frequency: "A", source: "imf", region: "Asia", unit: "%", params: { country: "JP", indicator: "NGDP_RPCH" } },
		{ id: "imf:JP:PCPIPCH", name: "Inflation (Japan)", group: "IMF Outlook", frequency: "A", source: "imf", region: "Asia", unit: "%", params: { country: "JP", indicator: "PCPIPCH" } },

		// ── IMF EM ──
		{ id: "imf:CN:NGDP_RPCH", name: "GDP Growth (China)", group: "IMF Outlook", frequency: "A", source: "imf", region: "EM", unit: "%", params: { country: "CN", indicator: "NGDP_RPCH" } },
		{ id: "imf:BR:NGDP_RPCH", name: "GDP Growth (Brazil)", group: "IMF Outlook", frequency: "A", source: "imf", region: "EM", unit: "%", params: { country: "BR", indicator: "NGDP_RPCH" } },
		{ id: "imf:CN:PCPIPCH", name: "Inflation (China)", group: "IMF Outlook", frequency: "A", source: "imf", region: "EM", unit: "%", params: { country: "CN", indicator: "PCPIPCH" } },
		{ id: "imf:BR:PCPIPCH", name: "Inflation (Brazil)", group: "IMF Outlook", frequency: "A", source: "imf", region: "EM", unit: "%", params: { country: "BR", indicator: "PCPIPCH" } },
	];

	export function getCatalog(): IndicatorEntry[] {
		return CATALOG;
	}

	export function getEntryById(id: string): IndicatorEntry | undefined {
		return CATALOG.find((e) => e.id === id);
	}

	// Seed expandedGroups once CATALOG is in scope. Default = all groups +
	// Favorites pseudo-group expanded so the picker is never empty on load.
	$effect(() => {
		if (expandedGroups.size === 0) {
			const allGroups = new Set<string>([FAVORITES_GROUP]);
			for (const e of CATALOG) allGroups.add(e.group);
			expandedGroups = allGroups;
		}
	});

	let filtered = $derived.by(() => {
		let items = CATALOG;
		if (sourceFilter !== "All") {
			items = items.filter((e) => e.source === sourceFilter);
		}
		if (regionFilter !== "All") {
			items = items.filter((e) => e.region === regionFilter);
		}
		if (frequencyFilter !== "All") {
			items = items.filter((e) => e.frequency === frequencyFilter);
		}
		if (searchState.debounced.trim()) {
			const q = searchState.debounced.trim().toLowerCase();
			items = items.filter(
				(e) =>
					e.name.toLowerCase().includes(q) ||
					e.group.toLowerCase().includes(q) ||
					e.id.toLowerCase().includes(q),
			);
		}
		return items;
	});

	let groupedFiltered = $derived.by(() => {
		const groups = new Map<string, IndicatorEntry[]>();
		// Pin a virtual "Favorites" group at the top whenever the user has
		// any favorites that pass the active filters. Favourites used to be
		// decorative — the ★ button toggled state but no UI surfaced it.
		if (favorites.size > 0) {
			const favItems = filtered.filter((e) => favorites.has(e.id));
			if (favItems.length > 0) {
				groups.set(FAVORITES_GROUP, favItems);
			}
		}
		for (const item of filtered) {
			const list = groups.get(item.group) ?? [];
			list.push(item);
			groups.set(item.group, list);
		}
		return groups;
	});

	let atLimit = $derived(selected.size >= MAX_SERIES);
	let nearLimit = $derived(selected.size >= WARN_THRESHOLD);

	function toggleGroup(group: string) {
		const next = new Set(expandedGroups);
		if (next.has(group)) next.delete(group);
		else next.add(group);
		expandedGroups = next;
	}

	const FREQ_COLORS: Record<string, string> = {
		D: "var(--ii-chart-1)",
		M: "var(--ii-chart-2)",
		Q: "var(--ii-chart-3)",
		A: "var(--ii-chart-4)",
	};
</script>

<aside class="picker">
	<input
		class="picker-search"
		type="search"
		placeholder="Search indicators…"
		value={searchState.current}
		oninput={(e) => { searchState.current = e.currentTarget.value; }}
	/>

	<div class="chip-row">
		{#each REGIONS as r (r)}
			<button
				class="chip"
				class:chip--active={regionFilter === r}
				onclick={() => (regionFilter = r)}
			>
				{r}
			</button>
		{/each}
	</div>

	<div class="chip-row">
		{#each FREQUENCIES as f (f)}
			<button
				class="chip"
				class:chip--active={frequencyFilter === f}
				onclick={() => (frequencyFilter = f)}
			>
				{f === "All" ? "All" : FREQ_LABELS[f]}
			</button>
		{/each}
	</div>

	<div class="chip-row">
		{#each SOURCES as s (s)}
			<button
				class="chip"
				class:chip--active={sourceFilter === s}
				onclick={() => (sourceFilter = s)}
			>
				{SOURCE_LABELS[s]}
			</button>
		{/each}
	</div>

	{#if nearLimit && !atLimit}
		<div class="picker-warning">Approaching series limit ({selected.size}/{MAX_SERIES})</div>
	{/if}

	<div class="picker-list">
		{#each [...groupedFiltered] as [group, items] (group)}
			<button class="group-header" onclick={() => toggleGroup(group)}>
				<span class="group-chevron" class:group-chevron--open={expandedGroups.has(group) || searchState.debounced.trim() !== ""}>&#9656;</span>
				<span class="group-name">{group}</span>
				<span class="group-count">{items.length}</span>
			</button>

			{#if expandedGroups.has(group) || searchState.debounced.trim() !== ""}
				<div transition:slide={{ duration: 150 }}>
					{#each items as entry (entry.id)}
						{@const isSelected = selected.has(entry.id)}
						{@const isFav = favorites.has(entry.id)}
						<div class="indicator-row" class:indicator-row--selected={isSelected}>
							<button
								class="indicator-btn"
								disabled={atLimit && !isSelected}
								title={atLimit && !isSelected ? "Maximum 8 series reached" : entry.name}
								onclick={() => onToggle(entry.id)}
							>
								<span class="indicator-check">{isSelected ? "✓" : ""}</span>
								<span class="indicator-name">{entry.name}</span>
								<span class="freq-badge" style:background={FREQ_COLORS[entry.frequency]}>{entry.frequency}</span>
							</button>
							{#if onToggleFavorite}
								<button
									class="fav-btn"
									class:fav-btn--active={isFav}
									title={isFav ? "Remove from favorites" : "Add to favorites"}
									onclick={() => onToggleFavorite(entry.id)}
								>
									{isFav ? "★" : "☆"}
								</button>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		{/each}

		{#if filtered.length === 0}
			<div class="picker-empty">No indicators match your filters</div>
		{/if}
	</div>
</aside>

<style>
	.picker {
		display: flex;
		flex-direction: column;
		gap: 8px;
		min-width: 280px;
		max-width: 320px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		padding: 12px;
		overflow-y: auto;
		max-height: 600px;
	}

	.picker-search {
		width: 100%;
		height: var(--ii-space-control-height-sm, 28px);
		padding: 0 8px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-label, 0.75rem);
		font-family: var(--ii-font-sans);
	}

	.picker-search::placeholder {
		color: var(--ii-text-muted);
	}

	.chip-row {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}

	.chip {
		padding: 2px 8px;
		font-size: 11px;
		font-weight: 500;
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		background: var(--ii-surface);
		color: var(--ii-text-secondary);
		cursor: pointer;
		transition: all 100ms ease;
	}

	.chip:hover {
		background: var(--ii-surface-alt);
	}

	.chip--active {
		background: var(--ii-brand-primary);
		color: white;
		border-color: var(--ii-brand-primary);
	}

	.picker-warning {
		padding: 4px 8px;
		font-size: 11px;
		font-weight: 500;
		color: var(--ii-warning);
		background: color-mix(in srgb, var(--ii-warning) 10%, transparent);
		border-radius: var(--ii-radius-sm, 6px);
		text-align: center;
	}

	.picker-list {
		display: flex;
		flex-direction: column;
	}

	.group-header {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 6px 4px;
		border: none;
		background: none;
		cursor: pointer;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.group-header:hover {
		color: var(--ii-text-primary);
	}

	.group-chevron {
		font-size: 10px;
		transition: transform 150ms ease;
	}

	.group-chevron--open {
		transform: rotate(90deg);
	}

	.group-name {
		flex: 1;
		text-align: left;
	}

	.group-count {
		font-size: 10px;
		color: var(--ii-text-muted);
		font-weight: 400;
	}

	.indicator-row {
		display: flex;
		align-items: center;
		padding-left: 8px;
	}

	.indicator-row--selected {
		background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
	}

	.indicator-btn {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 4px;
		border: none;
		background: none;
		cursor: pointer;
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		text-align: left;
	}

	.indicator-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.indicator-btn:hover:not(:disabled) {
		background: var(--ii-surface-alt);
		border-radius: 4px;
	}

	.indicator-check {
		width: 14px;
		font-size: 11px;
		color: var(--ii-brand-primary);
		font-weight: 700;
	}

	.indicator-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.freq-badge {
		padding: 1px 5px;
		font-size: 9px;
		font-weight: 700;
		color: white;
		border-radius: 6px;
		letter-spacing: 0.04em;
	}

	.fav-btn {
		border: none;
		background: none;
		cursor: pointer;
		color: var(--ii-text-muted);
		font-size: 14px;
		padding: 4px;
	}

	.fav-btn--active {
		color: var(--ii-warning);
	}

	.picker-empty {
		padding: 16px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
