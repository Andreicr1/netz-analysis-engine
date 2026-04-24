<!--
	FilterChipRow — horizontal strip of applied-filter pills above the
	datagrid.

	Stateless by design: chips are derived from `filters` inline; every
	removal is routed through `onFiltersChange` so the URL remains the
	single source of truth (see plan §G.SCREENER risk 3 — chip removal
	and rail checkbox must not diverge).
-->
<script module lang="ts">
	export interface DerivedChip {
		key: string;
		label: string;
		value: string;
		onRemove: () => void;
	}
</script>

<script lang="ts">
	import { formatCompactCurrency } from "@investintell/ui";
	import type { FilterState } from "./TerminalScreenerFilters.svelte";

	interface Props {
		filters: FilterState;
		onFiltersChange: (next: FilterState) => void;
	}

	let { filters, onFiltersChange }: Props = $props();

	const FUND_UNIVERSE_LABELS: Record<string, string> = {
		mutual_fund: "Mutual",
		etf: "ETF",
		closed_end: "CEF",
		interval_fund: "Interval",
		bdc: "BDC",
		money_market: "MMF",
		hedge_fund: "Hedge",
		private_fund: "Private",
		private_equity_fund: "PE",
		ucits: "UCITS",
	};

	function remove(key: string, value: string): () => void {
		return () => {
			const next: FilterState = {
				...filters,
				query: filters.query,
				fundUniverse: new Set(filters.fundUniverse),
				strategies: new Set(filters.strategies),
				geographies: new Set(filters.geographies),
				managerNames: [...filters.managerNames],
			};
			switch (key) {
				case "fundUniverse":
					next.fundUniverse.delete(value);
					break;
				case "query":
					next.query = "";
					break;
				case "strategy":
					next.strategies.delete(value);
					break;
				case "geography":
					next.geographies.delete(value);
					break;
				case "manager":
					next.managerNames = next.managerNames.filter((n) => n !== value);
					break;
				case "aum":
					next.aumMin = 0;
					next.aumMax = 0;
					break;
				case "return1y":
					next.returnMin = -999;
					next.returnMax = 999;
					break;
				case "expense":
					next.expenseMax = 10;
					break;
				case "elite":
					next.eliteOnly = false;
					break;
				case "sharpe":
					next.sharpeMin = "";
					next.sharpeMax = "";
					break;
				case "drawdown":
					next.drawdownMinPct = "";
					next.drawdownMaxPct = "";
					break;
				case "vol":
					next.volatilityMax = "";
					break;
				case "return10y":
					next.return10yMin = "";
					next.return10yMax = "";
					break;
			}
			onFiltersChange(next);
		};
	}

	function rangeLabel(lo: number | string | null, hi: number | string | null, suffix: string): string {
		const loStr = lo !== null && lo !== "" && !(typeof lo === "number" && (lo === 0 || lo === -999)) ? String(lo) : "";
		const hiStr = hi !== null && hi !== "" && !(typeof hi === "number" && (hi === 0 || hi === 999)) ? String(hi) : "";
		if (loStr && hiStr) return `${loStr}${suffix}–${hiStr}${suffix}`;
		if (loStr) return `≥${loStr}${suffix}`;
		if (hiStr) return `≤${hiStr}${suffix}`;
		return "";
	}

	const chips = $derived.by<DerivedChip[]>(() => {
		const out: DerivedChip[] = [];

		if (filters.query.trim()) {
			out.push({
				key: "query",
				label: "Search",
				value: filters.query.trim(),
				onRemove: remove("query", ""),
			});
		}
		for (const v of filters.fundUniverse) {
			out.push({
				key: `fundUniverse:${v}`,
				label: "Type",
				value: FUND_UNIVERSE_LABELS[v] ?? v,
				onRemove: remove("fundUniverse", v),
			});
		}
		for (const v of filters.strategies) {
			out.push({
				key: `strategy:${v}`,
				label: "Strategy",
				value: v,
				onRemove: remove("strategy", v),
			});
		}
		for (const v of filters.geographies) {
			out.push({
				key: `geography:${v}`,
				label: "Geo",
				value: v,
				onRemove: remove("geography", v),
			});
		}
		for (const v of filters.managerNames) {
			out.push({
				key: `manager:${v}`,
				label: "Manager",
				value: v,
				onRemove: remove("manager", v),
			});
		}
		if (filters.eliteOnly) {
			out.push({
				key: "elite",
				label: "Tier",
				value: "Elite only",
				onRemove: remove("elite", ""),
			});
		}
		if (filters.aumMin > 0 || filters.aumMax > 0) {
			const lo = filters.aumMin > 0 ? formatCompactCurrency(filters.aumMin) : "";
			const hi = filters.aumMax > 0 ? formatCompactCurrency(filters.aumMax) : "";
			let value: string;
			if (lo && hi) value = `${lo}–${hi}`;
			else if (lo) value = `≥${lo}`;
			else value = `≤${hi}`;
			out.push({ key: "aum", label: "AUM", value, onRemove: remove("aum", "") });
		}
		const ret1y = rangeLabel(
			filters.returnMin > -999 ? filters.returnMin : null,
			filters.returnMax < 999 ? filters.returnMax : null,
			"%",
		);
		if (ret1y) {
			out.push({ key: "return1y", label: "1Y Return", value: ret1y, onRemove: remove("return1y", "") });
		}
		if (filters.expenseMax < 10) {
			out.push({
				key: "expense",
				label: "Fee",
				value: `≤${filters.expenseMax}%`,
				onRemove: remove("expense", ""),
			});
		}
		const sharpe = rangeLabel(filters.sharpeMin || null, filters.sharpeMax || null, "");
		if (sharpe) out.push({ key: "sharpe", label: "Sharpe", value: sharpe, onRemove: remove("sharpe", "") });
		const dd = rangeLabel(filters.drawdownMinPct || null, filters.drawdownMaxPct || null, "%");
		if (dd) out.push({ key: "drawdown", label: "Drawdown", value: dd, onRemove: remove("drawdown", "") });
		if (filters.volatilityMax) {
			out.push({
				key: "vol",
				label: "Vol",
				value: `≤${filters.volatilityMax}%`,
				onRemove: remove("vol", ""),
			});
		}
		const ret10y = rangeLabel(filters.return10yMin || null, filters.return10yMax || null, "%");
		if (ret10y) out.push({ key: "return10y", label: "10Y Return", value: ret10y, onRemove: remove("return10y", "") });

		return out;
	});

	function clearAll() {
		onFiltersChange({
			query: "",
			fundUniverse: new Set(),
			strategies: new Set(),
			geographies: new Set(),
			aumMin: 0,
			aumMax: 0,
			returnMin: -999,
			returnMax: 999,
			expenseMax: 10,
			eliteOnly: false,
			managerNames: [],
			sharpeMin: "",
			sharpeMax: "",
			drawdownMinPct: "",
			drawdownMaxPct: "",
			volatilityMax: "",
			return10yMin: "",
			return10yMax: "",
		});
	}
</script>

{#if chips.length > 0}
	<div class="chip-row" role="region" aria-label="Applied filters">
		<span class="chip-row__label">FILTERS</span>
		<ul class="chip-row__list">
			{#each chips as chip (chip.key)}
				<li class="chip-row__item">
					<button
						type="button"
						class="chip"
						aria-label={`Remove ${chip.label} ${chip.value}`}
						onclick={chip.onRemove}
					>
						<span class="chip__label">{chip.label}</span>
						<span class="chip__sep">·</span>
						<span class="chip__value">{chip.value}</span>
						<span class="chip__x" aria-hidden="true">×</span>
					</button>
				</li>
			{/each}
		</ul>
		<button type="button" class="chip-row__clear" onclick={clearAll}>CLEAR ALL</button>
	</div>
{/if}

<style>
	.chip-row {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
		min-height: 28px;
		overflow-x: auto;
		overflow-y: hidden;
		scrollbar-width: thin;
		white-space: nowrap;
	}

	.chip-row__label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		flex-shrink: 0;
	}

	.chip-row__list {
		display: flex;
		gap: var(--terminal-space-2);
		list-style: none;
		margin: 0;
		padding: 0;
		flex: 1;
		min-width: 0;
	}

	.chip-row__item {
		display: inline-flex;
		flex-shrink: 0;
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: 2px var(--terminal-space-2);
		height: 20px;
		background: var(--terminal-bg-panel-raised);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-secondary);
		font-family: inherit;
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		line-height: 1;
		cursor: pointer;
		white-space: nowrap;
	}
	.chip:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}
	.chip:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.chip__label {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}
	.chip:hover .chip__label {
		color: var(--terminal-accent-amber);
	}
	.chip__sep {
		color: var(--terminal-fg-tertiary);
	}
	.chip__value {
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}
	.chip:hover .chip__value {
		color: var(--terminal-accent-amber);
	}
	.chip__x {
		margin-left: var(--terminal-space-1);
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-11);
	}
	.chip:hover .chip__x {
		color: var(--terminal-accent-amber);
	}

	.chip-row__clear {
		margin-left: auto;
		background: transparent;
		border: none;
		color: var(--terminal-fg-tertiary);
		font-family: inherit;
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		padding: 0 var(--terminal-space-2);
		flex-shrink: 0;
	}
	.chip-row__clear:hover {
		color: var(--terminal-accent-amber);
	}
	.chip-row__clear:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}
</style>
