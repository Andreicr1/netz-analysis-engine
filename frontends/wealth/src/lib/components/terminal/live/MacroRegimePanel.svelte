<!--
  MacroRegimePanel -- key macro indicators from FRED via macro_data.

  Fetches latest values for VIX, CPI, DXY, 10Y, IG/HY spreads,
  Fed Funds, Unemployment from GET /macro/fred?series_id={id}.
  Shows value + directional change arrow.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatPercent, formatNumber, formatBps } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface Indicator {
		label: string;
		seriesId: string;
		suffix: string;
		/** true = rising is danger (VIX, spreads), false = rising is positive */
		riseIsWarning: boolean;
	}

	const INDICATORS: Indicator[] = [
		{ label: "VIX", seriesId: "VIXCLS", suffix: "", riseIsWarning: true },
		{ label: "CPI (YoY)", seriesId: "CPI_YOY", suffix: "%", riseIsWarning: true },
		{ label: "DXY", seriesId: "DTWEXBGS", suffix: "", riseIsWarning: false },
		{ label: "10Y YIELD", seriesId: "DGS10", suffix: "%", riseIsWarning: false },
		{ label: "IG SPREAD", seriesId: "BAA10Y", suffix: "bp", riseIsWarning: true },
		{ label: "HY SPREAD", seriesId: "BAMLH0A0HYM2", suffix: "bp", riseIsWarning: true },
		{ label: "FED FUNDS", seriesId: "DFF", suffix: "%", riseIsWarning: false },
		{ label: "UNEMPLOYMENT", seriesId: "UNRATE", suffix: "%", riseIsWarning: true },
	];

	interface IndicatorValue {
		value: number | null;
		change: number | null;
	}

	let values = $state<Map<string, IndicatorValue>>(new Map());
	let loading = $state(true);

	$effect(() => {
		let cancelled = false;
		loading = true;

		const fetches = INDICATORS.map(async (ind) => {
			try {
				const res = await api.get<{
					series_id: string;
					data: Array<{ obs_date: string; value: number }>;
				}>(`/macro/fred?series_id=${encodeURIComponent(ind.seriesId)}`);

				if (cancelled) return;

				const data = res.data;
				if (data.length === 0) {
					values.set(ind.seriesId, { value: null, change: null });
					return;
				}

				const latestPoint = data[data.length - 1];
				const prevPoint = data.length >= 2 ? data[data.length - 2] : undefined;
				const latest = latestPoint?.value ?? null;
				const prev = prevPoint?.value ?? null;
				const change = latest != null && prev != null ? latest - prev : null;

				values = new Map(values).set(ind.seriesId, { value: latest, change });
			} catch {
				if (!cancelled) {
					values = new Map(values).set(ind.seriesId, { value: null, change: null });
				}
			}
		});

		Promise.all(fetches).then(() => {
			if (!cancelled) loading = false;
		});

		return () => { cancelled = true; };
	});

	function formatVal(v: number | null, suffix: string): string {
		if (v == null) return "\u2014";
		if (suffix === "%") return formatPercent(v / 100, 1);
		if (suffix === "bp") return formatBps(v / 100);
		return formatNumber(v, 1);
	}

	function changeArrow(change: number | null): string {
		if (change == null || Math.abs(change) < 0.001) return "\u2500";
		return change > 0 ? "\u25B2" : "\u25BC";
	}

	function changeClass(change: number | null, riseIsWarning: boolean): string {
		if (change == null || Math.abs(change) < 0.001) return "mr-neutral";
		if (change > 0) return riseIsWarning ? "mr-warn" : "mr-good";
		return riseIsWarning ? "mr-good" : "mr-warn";
	}

	function formatChange(change: number | null, suffix: string): string {
		if (change == null) return "";
		if (suffix === "bp") return `${change > 0 ? "+" : ""}${Math.round(change * 100)}`;
		if (suffix === "%") return `${change > 0 ? "+" : ""}${formatNumber(Math.abs(change), 1)}`;
		return `${change > 0 ? "+" : ""}${formatNumber(Math.abs(change), 1)}`;
	}
</script>

<div class="mr-root">
	<div class="mr-header">
		<span class="mr-label">MACRO REGIME</span>
	</div>

	<div class="mr-body">
		{#each INDICATORS as ind (ind.seriesId)}
			{@const v = values.get(ind.seriesId)}
			{@const val = v?.value ?? null}
			{@const chg = v?.change ?? null}
			<div class="mr-row">
				<span class="mr-key">{ind.label}</span>
				<span class="mr-val">
					{formatVal(val, ind.suffix)}
				</span>
				<span class="mr-change {changeClass(chg, ind.riseIsWarning)}">
					{changeArrow(chg)} {formatChange(chg, ind.suffix)}
				</span>
			</div>
		{/each}
	</div>
</div>

<style>
	.mr-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.mr-header {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.mr-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.mr-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: var(--terminal-space-1) 0;
	}

	.mr-row {
		display: grid;
		grid-template-columns: 1fr auto auto;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: 3px var(--terminal-space-2);
		height: 24px;
	}

	.mr-key {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.mr-val {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
		text-align: right;
		white-space: nowrap;
	}

	.mr-change {
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
		text-align: right;
		min-width: 48px;
		white-space: nowrap;
	}

	.mr-good {
		color: var(--terminal-status-success);
	}

	.mr-warn {
		color: var(--terminal-status-error);
	}

	.mr-neutral {
		color: var(--terminal-fg-muted);
	}
</style>
