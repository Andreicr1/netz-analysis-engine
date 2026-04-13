<!--
  RegimeTab — REGIME tab in the Builder results panel (right column).

  Three sections:
  1. Regime History Chart (S&P500 line + colored markArea bands per regime)
  2. Regime Metadata Panel (badge, stress bar, signal breakdown table)
  3. Allocation Bands Summary (Equity/FI/Alt/Cash min→center→max)
-->
<script lang="ts">
	import { getContext } from "svelte";
	import {
		createTerminalChartOptions,
		readTerminalTokens,
		formatPercent,
		formatNumber,
		formatDate,
	} from "@investintell/ui";
	import TerminalChart from "$lib/components/terminal/charts/TerminalChart.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import {
		taaRegimeLabel,
		taaRegimeColor,
		taaRegimePosture,
	} from "$lib/types/taa";
	import type { RegimeBands } from "$lib/types/taa";
	import type { EChartsOption } from "echarts";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// ── Regime overlay data ─────────────────────────────────────

	interface RegimeOverlay {
		dates: string[];
		spy_values: number[];
		regime_bands: Array<{ start: string; end: string; regime: string }>;
		period: string;
	}

	const PERIODS = ["1Y", "2Y", "3Y", "5Y"] as const;
	type Period = (typeof PERIODS)[number];

	let period = $state<Period>("3Y");
	let overlay = $state<RegimeOverlay | null>(null);
	let loading = $state(true);

	async function fetchOverlay() {
		loading = true;
		try {
			const res = await api.get(`/allocation/regime-overlay?period=${period}`);
			overlay = res as RegimeOverlay;
		} catch (e) {
			console.error("Failed to fetch regime overlay", e);
			overlay = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		// Track period reactively — reads period inside the effect body
		const _p = period;
		void fetchOverlay();
	});

	// ── Current regime (from existing endpoint) ──────────────────

	interface GlobalRegime {
		as_of_date: string;
		raw_regime: string;
		stress_score: number | null;
		signal_details: Record<string, string>;
	}

	let currentRegime = $state<GlobalRegime | null>(null);

	$effect(() => {
		(async () => {
			try {
				const res = await api.get("/allocation/regime");
				currentRegime = res as GlobalRegime;
			} catch {
				currentRegime = null;
			}
		})();
	});

	// ── Chart options ────────────────────────────────────────────

	const REGIME_COLORS: Record<string, { label: string }> = {
		RISK_ON: { label: "Expansion" },
		RISK_OFF: { label: "Defensive" },
		CRISIS: { label: "Stress" },
		INFLATION: { label: "Inflation" },
	};

	function regimeChartColor(regime: string): string {
		const tokens = readTerminalTokens();
		const map: Record<string, string> = {
			RISK_ON: tokens.statusSuccess,
			RISK_OFF: tokens.statusWarn,
			CRISIS: tokens.statusError,
			INFLATION: tokens.accentViolet,
		};
		return map[regime] ?? tokens.fgMuted;
	}

	const chartOption = $derived.by<EChartsOption>(() => {
		if (!overlay || overlay.dates.length === 0) {
			return createTerminalChartOptions({
				series: [],
				showLegend: false,
			});
		}

		const tokens = readTerminalTokens();

		const markAreaData = overlay.regime_bands.map((band) => {
			const pair: [Record<string, unknown>, Record<string, unknown>] = [
				{
					xAxis: band.start,
					itemStyle: {
						color: regimeChartColor(band.regime),
						opacity: 0.12,
					},
				},
				{ xAxis: band.end },
			];
			return pair;
		});

		return createTerminalChartOptions({
			series: [
				{
					type: "line",
					name: "S&P 500",
					data: overlay.dates.map((d, i) => [d, overlay!.spy_values[i]]),
					lineStyle: { width: 1.5, color: tokens.accentAmber },
					itemStyle: { color: tokens.accentAmber },
					symbol: "none",
					smooth: false,
					markArea: {
						silent: true,
						data: markAreaData,
					},
				},
			],
			yAxis: {
				type: "value",
				axisLabel: { formatter: (v: number) => formatNumber(v, 0) },
			},
			showLegend: false,
		});
	});

	// ── Signal breakdown parsing ─────────────────────────────────

	const SIGNAL_LABELS: Record<string, string> = {
		vix: "VIX",
		yield_curve_spread: "Yield Curve",
		cpi_yoy: "CPI YoY",
		sahm_rule: "Sahm Rule",
		hy_oas: "HY OAS",
		baa_spread: "Baa Spread",
		fed_funds_delta_6m: "Fed Funds Delta",
		dxy_zscore: "DXY Z-Score",
		energy_shock: "Energy Shock",
		cfnai: "CFNAI",
	};

	interface SignalRow {
		key: string;
		label: string;
		value: string;
		status: string;
	}

	function parseSignalDetails(details: Record<string, string>): SignalRow[] {
		const rows: SignalRow[] = [];
		for (const [key, raw] of Object.entries(details)) {
			if (key === "composite_stress" || key === "decision") continue;
			const label = SIGNAL_LABELS[key];
			if (!label) continue;

			// Try to extract numeric value and parenthetical status
			const numMatch = raw.match(/[=:]?\s*([\d.\-]+)/);
			const statusMatch = raw.match(/\(([^)]+)\)/);
			rows.push({
				key,
				label,
				value: numMatch?.[1] ?? raw,
				status: statusMatch?.[1] ?? raw,
			});
		}
		return rows;
	}

	const signalRows = $derived(
		currentRegime?.signal_details ? parseSignalDetails(currentRegime.signal_details) : [],
	);

	const decisionText = $derived(currentRegime?.signal_details?.["decision"] ?? null);

	// ── Regime duration from overlay ─────────────────────────────

	const regimeDurationDays = $derived.by(() => {
		if (!overlay?.regime_bands.length) return null;
		const last = overlay.regime_bands.at(-1);
		if (!last) return null;
		const days = Math.ceil(
			(new Date(last.end).getTime() - new Date(last.start).getTime()) / 86400000,
		);
		return days;
	});

	// ── Allocation bands from workspace ──────────────────────────

	const regimeBands: RegimeBands | null = $derived(workspace.regimeBands ?? null);

	const BAND_ORDER: Record<string, string> = {
		equity: "Equity",
		fi: "Fixed Income",
		alt: "Alternatives",
		cash: "Cash",
	};

	interface BandRow {
		label: string;
		min: number;
		center: number | null;
		max: number;
	}

	const bandRows = $derived.by<BandRow[]>(() => {
		if (!regimeBands?.effective_bands) return [];
		const agg: Record<string, { min: number; center: number; max: number }> = {};
		for (const [blockId, band] of Object.entries(regimeBands.effective_bands)) {
			let cls = "other";
			if (
				blockId.startsWith("na_equity") ||
				blockId.startsWith("dm_") ||
				blockId.startsWith("em_") ||
				blockId.startsWith("intl_equity")
			)
				cls = "equity";
			else if (blockId.startsWith("fi_")) cls = "fi";
			else if (blockId.startsWith("alt_")) cls = "alt";
			else if (blockId === "cash") cls = "cash";

			const entry = agg[cls] ?? (agg[cls] = { min: 0, center: 0, max: 0 });
			entry.min += band.min;
			entry.center += band.center ?? (band.min + band.max) / 2;
			entry.max += band.max;
		}
		const rows: BandRow[] = [];
		for (const [key, label] of Object.entries(BAND_ORDER)) {
			const a = agg[key];
			if (!a) continue;
			rows.push({ label, min: a.min, center: a.center, max: a.max });
		}
		return rows;
	});
</script>

<div class="rt-root">
	<!-- Section 1: Regime History Chart -->
	<div class="rt-section">
		<div class="rt-section-header">
			<span class="rt-section-title">REGIME HISTORY</span>
			<div class="rt-period-group">
				{#each PERIODS as p (p)}
					<button
						type="button"
						class="rt-period-btn"
						class:rt-period-btn--active={period === p}
						onclick={() => { period = p; }}
					>
						{p}
					</button>
				{/each}
			</div>
		</div>

		<TerminalChart
			option={chartOption}
			height={300}
			ariaLabel="S&P 500 with regime classification overlay"
			empty={!overlay || overlay.dates.length === 0}
			emptyMessage="NO REGIME DATA"
			{loading}
		/>
	</div>

	<!-- Section 2: Regime Metadata Panel -->
	<div class="rt-section">
		<div class="rt-section-header">
			<span class="rt-section-title">CURRENT REGIME</span>
		</div>

		{#if currentRegime}
			<div class="rt-meta-row">
				<span
					class="rt-badge"
					style="background: {taaRegimeColor(currentRegime.raw_regime)}; color: var(--terminal-fg-inverted);"
				>
					{taaRegimeLabel(currentRegime.raw_regime)}
				</span>
				<span class="rt-meta-date">as of {formatDate(currentRegime.as_of_date)}</span>
				{#if regimeDurationDays !== null}
					<span class="rt-meta-duration">{regimeDurationDays}d</span>
				{/if}
			</div>

			<div class="rt-stress">
				<span class="rt-stress-label">STRESS</span>
				<div class="rt-stress-track">
					<div
						class="rt-stress-fill"
						style="width: {currentRegime.stress_score ?? 0}%; background: {taaRegimeColor(currentRegime.raw_regime)};"
					></div>
				</div>
				<span class="rt-stress-value">{currentRegime.stress_score ?? 0}/100</span>
			</div>

			<!-- Signal breakdown table -->
			{#if signalRows.length > 0}
				<table class="rt-signal-table">
					<thead>
						<tr>
							<th class="rt-sig-th">Signal</th>
							<th class="rt-sig-th rt-sig-th--right">Value</th>
							<th class="rt-sig-th rt-sig-th--right">Status</th>
						</tr>
					</thead>
					<tbody>
						{#each signalRows as row (row.key)}
							<tr class="rt-sig-row">
								<td class="rt-sig-td">{row.label}</td>
								<td class="rt-sig-td rt-sig-td--right rt-sig-td--mono">{row.value}</td>
								<td class="rt-sig-td rt-sig-td--right rt-sig-td--status">{row.status}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}

			{#if decisionText}
				<div class="rt-decision">{decisionText}</div>
			{/if}
		{:else}
			<div class="rt-empty">Regime data unavailable</div>
		{/if}
	</div>

	<!-- Section 3: Allocation Bands Summary -->
	<div class="rt-section">
		<div class="rt-section-header">
			<span class="rt-section-title">ALLOCATION BANDS</span>
		</div>

		{#if bandRows.length > 0}
			<div class="rt-bands">
				{#each bandRows as row (row.label)}
					<div class="rt-band-row">
						<span class="rt-band-label">{row.label}</span>
						<span class="rt-band-range">
							{formatPercent(row.min, 1)}
							<span class="rt-band-arrow">&rarr;</span>
							{formatPercent(row.center ?? row.min, 1)}
							<span class="rt-band-arrow">&rarr;</span>
							{formatPercent(row.max, 1)}
						</span>
					</div>
				{/each}
			</div>

			{#if regimeBands}
				<div class="rt-posture">{taaRegimePosture(regimeBands.raw_regime)}</div>
			{/if}
		{:else}
			<div class="rt-empty">No allocation band data</div>
		{/if}
	</div>
</div>

<style>
	.rt-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
	}

	.rt-section {
		border-bottom: var(--terminal-border-hairline);
		padding-bottom: var(--terminal-space-2);
	}

	.rt-section:last-child {
		border-bottom: none;
	}

	.rt-section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--terminal-space-2);
	}

	.rt-section-title {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}

	/* Period selector */
	.rt-period-group {
		display: flex;
		gap: 1px;
	}

	.rt-period-btn {
		padding: 2px 8px;
		background: transparent;
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.rt-period-btn:hover {
		color: var(--terminal-accent-amber);
	}

	.rt-period-btn--active {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}

	/* Metadata panel */
	.rt-meta-row {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		margin-bottom: var(--terminal-space-2);
	}

	.rt-badge {
		display: inline-block;
		padding: 1px 6px;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.rt-meta-date {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}

	.rt-meta-duration {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		color: var(--terminal-fg-secondary);
	}

	/* Stress bar */
	.rt-stress {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		margin-bottom: var(--terminal-space-2);
	}

	.rt-stress-label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		min-width: 40px;
	}

	.rt-stress-track {
		flex: 1;
		height: 4px;
		background: var(--terminal-fg-muted);
	}

	.rt-stress-fill {
		height: 100%;
		transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
	}

	.rt-stress-value {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		min-width: 48px;
		text-align: right;
	}

	/* Signal table */
	.rt-signal-table {
		width: 100%;
		border-collapse: collapse;
		margin-bottom: var(--terminal-space-2);
	}

	.rt-sig-th {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		text-align: left;
		font-size: var(--terminal-text-10);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		border-bottom: var(--terminal-border-hairline);
	}

	.rt-sig-th--right {
		text-align: right;
	}

	.rt-sig-row {
		border-bottom: var(--terminal-border-hairline);
	}

	.rt-sig-td {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-size: var(--terminal-text-11);
	}

	.rt-sig-td--right {
		text-align: right;
	}

	.rt-sig-td--mono {
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}

	.rt-sig-td--status {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}

	/* Decision footnote */
	.rt-decision {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-left: 2px solid var(--terminal-fg-muted);
	}

	/* Allocation bands */
	.rt-bands {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.rt-band-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding: var(--terminal-space-1) var(--terminal-space-2);
	}

	.rt-band-label {
		font-size: var(--terminal-text-10);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}

	.rt-band-range {
		color: var(--terminal-fg-primary);
		font-weight: 600;
	}

	.rt-band-arrow {
		color: var(--terminal-fg-muted);
	}

	.rt-posture {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		margin-top: var(--terminal-space-1);
	}

	.rt-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 60px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}
</style>
