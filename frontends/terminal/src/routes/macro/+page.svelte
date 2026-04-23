<script lang="ts">
	import "@investintell/ui/styles/surfaces/macro";
	import { getContext } from "svelte";
	import { createClientApiClient, createRegimePlotStore } from "@investintell/ii-terminal-core";
	import AssetDrawer from "@investintell/ii-terminal-core/components/terminal/macro/AssetDrawer.svelte";
	import CBPanel, {
		type CbEvent,
	} from "@investintell/ii-terminal-core/components/terminal/macro/CBPanel.svelte";
	import CrossAssetPanel, {
		type CrossAssetPoint,
	} from "@investintell/ii-terminal-core/components/terminal/macro/CrossAssetPanel.svelte";
	import EconPanel, {
		type EconRow,
	} from "@investintell/ii-terminal-core/components/terminal/macro/EconPanel.svelte";
	import LiquidityPanel from "@investintell/ii-terminal-core/components/terminal/macro/LiquidityPanel.svelte";
	import MacroNewsFeed from "@investintell/ii-terminal-core/components/terminal/macro/MacroNewsFeed.svelte";
	import RegimePlot from "@investintell/ii-terminal-core/components/terminal/macro/RegimePlot.svelte";
	import type { RegimeTrailPoint } from "@investintell/ii-terminal-core/components/terminal/macro/regime-plot-store.svelte";

	interface CrossAssetPointApi {
		symbol: string;
		name: string;
		sector: CrossAssetPoint["sector"];
		last_value: number | null;
		change_pct: number | null;
		unit: string;
		sparkline: number[];
	}

	interface CrossAssetResponseApi {
		assets: CrossAssetPointApi[];
	}

	interface RegimeResponseApi {
		raw_regime: string;
		stress_score: number | null;
	}

	interface DimensionScoreApi {
		score: number;
	}

	interface ScoresResponseApi {
		regions: Record<string, { dimensions: Record<string, DimensionScoreApi> }>;
	}

	interface FredPointApi {
		obs_date: string;
		value: number;
		source?: string;
	}

	interface FredResponseApi {
		data: FredPointApi[];
	}

	interface CbEventApi {
		central_bank: string;
		meeting_date: string;
		current_rate_pct: number;
		expected_change_bps: number;
	}

	interface CbCalendarResponseApi {
		events: CbEventApi[];
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	const simStore = createRegimePlotStore();

	let crossAssets = $state<CrossAssetPoint[]>([]);
	let crossAssetsLoading = $state(true);
	let trailPoints = $state<RegimeTrailPoint[]>([]);
	let livePin = $state({ g: 0, i: 0 });
	let activeRegime = $state("-");
	let nfci = $state<number | null>(null);
	let nfciHistory = $state<number[]>([]);
	let liquidityLoading = $state(true);
	let cbEvents = $state<CbEvent[]>([]);
	let cbLoading = $state(true);
	let econRows = $state<EconRow[]>([]);
	let econLoading = $state(true);
	let focusAsset = $state<CrossAssetPoint | null>(null);
	let fetchError = $state(false);

	const regimeLabel = $derived(activeRegime && activeRegime !== "-" ? activeRegime : "STANDBY");
	const liquidityLabel = $derived(nfci === null ? "PENDING" : nfci > 0.5 ? "TIGHT" : nfci < -0.5 ? "LOOSE" : "NEUTRAL");
	const sentimentAssets = $derived(
		[...crossAssets]
			.sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0))
			.slice(0, 6),
	);

	function scoreToCoordinate(score: number | null | undefined): number {
		if (score == null) return 0;
		return (score / 100) * 2 - 1;
	}

	function mapCrossAsset(asset: CrossAssetPointApi): CrossAssetPoint {
		return {
			symbol: asset.symbol,
			name: asset.name,
			sector: asset.sector,
			lastValue: asset.last_value ?? null,
			changePct: asset.change_pct ?? null,
			unit: asset.unit,
			sparkline: asset.sparkline ?? [],
		};
	}

	function mapCbEvent(event: CbEventApi): CbEvent {
		return {
			centralBank: event.central_bank,
			meetingDate: event.meeting_date,
			currentRatePct: event.current_rate_pct,
			expectedChangeBps: event.expected_change_bps,
		};
	}

	function mapEconRows(scores: ScoresResponseApi): EconRow[] {
		const us = scores.regions.US ?? scores.regions.us;
		const dimensions = us?.dimensions ?? {};
		return Object.entries(dimensions).map(([key, dim]) => ({
			name: key.replace(/_/g, " ").toUpperCase(),
			period: "LATEST",
			actual: dim.score ?? null,
			consensus: 50,
			unit: "idx",
			surprise: ((dim.score ?? 50) - 50) / 10,
		}));
	}

	function sparkPoints(values: number[], width = 74, height = 26): string {
		if (values.length < 2) return "";
		const min = Math.min(...values);
		const max = Math.max(...values);
		const range = max - min || 1;
		return values
			.map((value, index) => {
				const x = (index / (values.length - 1)) * width;
				const y = height - ((value - min) / range) * height;
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(" ");
	}

	function formatCompact(value: number | null): string {
		if (value === null) return "-";
		if (Math.abs(value) >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
		if (Math.abs(value) >= 100) return value.toFixed(0);
		return value.toFixed(2);
	}

	async function fetchAssetSeries(symbol: string): Promise<FredPointApi[]> {
		try {
			const data = await api.get<FredResponseApi>(`/macro/fred?series_id=${symbol}`);
			return data.data ?? [];
		} catch {
			return [];
		}
	}

	async function fetchAllData(signal: AbortSignal) {
		fetchError = false;

		const crossAssetPromise = api
			.get<CrossAssetResponseApi>("/macro/cross-asset", undefined, { signal })
			.then((data) => {
				crossAssets = (data.assets ?? []).map(mapCrossAsset);
			})
			.finally(() => {
				crossAssetsLoading = false;
			});

		const regimePromise = Promise.all([
			api.get<{ points: RegimeTrailPoint[] }>("/macro/regime/trail", undefined, { signal }),
			api.get<RegimeResponseApi>("/macro/regime", undefined, { signal }),
			api.get<ScoresResponseApi>("/macro/scores", undefined, { signal }),
		])
			.then(([trail, regime, scores]) => {
				trailPoints = trail.points ?? [];
				activeRegime = regime.raw_regime ?? "-";
				const us = scores.regions.US ?? scores.regions.us;
				livePin = {
					g: scoreToCoordinate(us?.dimensions?.growth?.score),
					i: scoreToCoordinate(us?.dimensions?.inflation?.score),
				};
				econRows = mapEconRows(scores);
			})
			.finally(() => {
				econLoading = false;
			});

		const liquidityPromise = api
			.get<FredResponseApi>("/macro/fred?series_id=NFCI", undefined, { signal })
			.then((data) => {
				const points = data.data ?? [];
				nfciHistory = points.slice(-24).map((point) => point.value);
				nfci = points.length ? points[points.length - 1]!.value : null;
			})
			.finally(() => {
				liquidityLoading = false;
			});

		const cbPromise = api
			.get<CbCalendarResponseApi>("/macro/cb-calendar", undefined, { signal })
			.then((data) => {
				cbEvents = (data.events ?? []).map(mapCbEvent);
			})
			.finally(() => {
				cbLoading = false;
			});

		try {
			await Promise.all([crossAssetPromise, regimePromise, liquidityPromise, cbPromise]);
		} catch (error) {
			if (error instanceof DOMException && error.name === "AbortError") return;
			fetchError = true;
		}
	}

	$effect(() => {
		const ac = new AbortController();
		fetchAllData(ac.signal);
		const timer = setInterval(() => fetchAllData(ac.signal), 5 * 60 * 1000);
		return () => {
			ac.abort();
			clearInterval(timer);
		};
	});
</script>

<div class="macro-desk" data-macro-root data-surface="macro">
	<div class="macro-toolbar">
		<div class="macro-group">
			<span class="macro-label">REGION</span>
			<div class="macro-seg" aria-label="Region">
				<button type="button" class="is-on">GLOBAL</button>
				<button type="button">US</button>
				<button type="button">EU</button>
				<button type="button">ASIA</button>
				<button type="button">BR</button>
			</div>
		</div>
		<div class="macro-group">
			<span class="macro-label">WINDOW</span>
			<div class="macro-seg macro-seg--tight" aria-label="Window">
				<button type="button">1W</button>
				<button type="button">1M</button>
				<button type="button">3M</button>
				<button type="button">YTD</button>
				<button type="button">1Y</button>
				<button type="button" class="is-on">5Y</button>
			</div>
		</div>
		<span class="macro-pill" class:macro-regime--risk-off={activeRegime.includes("OFF") || activeRegime.includes("RISK")}>
			REGIME · {regimeLabel}
		</span>
		<span class="macro-pill macro-pill--liq">LIQ · {liquidityLabel}</span>
		<span class="macro-toolbar-spacer"></span>
		<button type="button" class="compare-btn">+ COMPARE</button>
		{#if fetchError}
			<span class="macro-toolbar-error">DATA ERROR</span>
		{/if}
	</div>

	<div class="macro-grid">
		<div class="macro-col macro-col--left">
			<CrossAssetPanel assets={crossAssets} loading={crossAssetsLoading} onAssetSelect={(asset) => (focusAsset = asset)} />
		</div>

		<div class="macro-col macro-col--center">
			<div class="macro-center-upper">
				<div class="macro-regime-panel">
					<RegimePlot
						{activeRegime}
						{livePin}
						simulatedPin={simStore.simPin}
						trail={trailPoints}
						onSimulate={(pin) => simStore.set(pin)}
					/>
				</div>
				<div class="macro-factor-panel">
					<LiquidityPanel nfci={nfci} history={nfciHistory} loading={liquidityLoading} />
					<section class="sentiment-panel" aria-label="Sentiment and positioning">
						<header class="panel-title">SENTIMENT & POSITIONING</header>
						{#if crossAssetsLoading}
							<div class="sentiment-loading">LOADING...</div>
						{:else}
							<div class="sentiment-grid">
								{#each sentimentAssets as asset (asset.symbol)}
									<button type="button" class="sentiment-tile" onclick={() => (focusAsset = asset)}>
										<span class="sentiment-name">{asset.symbol}</span>
										<span class="sentiment-value">{formatCompact(asset.lastValue)}</span>
										<span class:up={(asset.changePct ?? 0) >= 0} class:down={(asset.changePct ?? 0) < 0}>
											{asset.changePct === null ? "-" : `${asset.changePct > 0 ? "+" : ""}${asset.changePct.toFixed(2)}%`}
										</span>
										<svg viewBox="0 0 74 26" preserveAspectRatio="none" aria-hidden="true">
											<polyline
												points={sparkPoints(asset.sparkline.slice(-24))}
												fill="none"
												stroke={(asset.changePct ?? 0) >= 0 ? "var(--ii-success)" : "var(--ii-danger)"}
												stroke-width="1"
												vector-effect="non-scaling-stroke"
											/>
										</svg>
									</button>
								{/each}
							</div>
						{/if}
					</section>
				</div>
			</div>
			<div class="macro-center-lower">
				<CBPanel events={cbEvents} loading={cbLoading} />
				<EconPanel rows={econRows} loading={econLoading} />
			</div>
		</div>

		<div class="macro-col macro-col--right">
			<MacroNewsFeed active />
		</div>
	</div>

	<AssetDrawer asset={focusAsset} onClose={() => (focusAsset = null)} fetchSeries={fetchAssetSeries} />
</div>

<style>
	.macro-desk {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
		background: var(--ii-bg);
		font-family: var(--ii-font-mono);
	}
	.macro-toolbar {
		display: flex;
		flex-shrink: 0;
		align-items: center;
		gap: 14px;
		height: 30px;
		padding: 0 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface);
	}
	.macro-group {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.macro-label {
		color: var(--ii-text-muted);
		font-size: 9px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.macro-seg {
		display: flex;
		border: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}
	.macro-seg button {
		height: 20px;
		padding: 0 11px;
		border: 0;
		border-right: 1px solid var(--ii-border-subtle);
		background: transparent;
		color: var(--ii-text-secondary);
		font: inherit;
		font-size: 10px;
		letter-spacing: 0.04em;
	}
	.macro-seg--tight button {
		padding-inline: 9px;
	}
	.macro-seg button:last-child {
		border-right: 0;
	}
	.macro-seg button.is-on {
		background: var(--ii-brand-primary);
		color: var(--ii-bg);
		font-weight: 700;
	}
	.macro-pill,
	.compare-btn {
		height: 20px;
		border: 1px solid var(--ii-terminal-accent-dim);
		background: rgba(255, 150, 90, 0.08);
		color: var(--ii-brand-primary);
		font: inherit;
		font-size: 10px;
		letter-spacing: 0.06em;
		display: inline-flex;
		align-items: center;
		padding: 0 10px;
	}
	.macro-pill--liq {
		border-color: var(--ii-terminal-up-dim);
		background: rgba(61, 211, 154, 0.08);
		color: var(--ii-success);
	}
	.compare-btn {
		border-color: var(--ii-border-subtle);
		background: var(--ii-surface-alt);
		color: var(--ii-text-tertiary);
	}
	.compare-btn:hover {
		border-color: var(--ii-brand-primary);
		color: var(--ii-brand-primary);
	}
	.macro-toolbar-spacer {
		flex: 1;
	}
	.macro-toolbar-error {
		color: var(--ii-danger);
		font-size: 10px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.macro-regime--risk-off {
		color: var(--ii-danger);
	}
	.macro-grid {
		display: grid;
		flex: 1;
		grid-template-columns: 376px minmax(660px, 1fr) 356px;
		gap: 1px;
		min-height: 0;
		overflow: hidden;
		background: var(--ii-border-subtle);
	}
	.macro-col {
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface);
	}
	.macro-col--center {
		display: grid;
		grid-template-rows: minmax(420px, 1.45fr) minmax(238px, 0.75fr);
		gap: 1px;
		overflow: hidden;
		background: var(--ii-border-subtle);
	}
	.macro-center-upper {
		display: grid;
		grid-template-columns: minmax(420px, 1.05fr) minmax(380px, 1fr);
		gap: 1px;
		min-height: 0;
		background: var(--ii-border-subtle);
	}
	.macro-regime-panel,
	.macro-factor-panel,
	.macro-center-lower {
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface);
	}
	.macro-factor-panel {
		display: grid;
		grid-template-rows: 150px 1fr;
		gap: 1px;
		background: var(--ii-border-subtle);
	}
	.macro-center-lower {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 1px;
		background: var(--ii-border-subtle);
	}
	.macro-col--right {
		display: flex;
		flex-direction: column;
		background: var(--ii-surface);
	}
	.macro-col--right > :global(*) {
		flex: 1;
		min-height: 0;
	}
	.panel-title {
		height: 28px;
		padding: 8px 12px 0;
		color: var(--ii-text-muted);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.sentiment-panel {
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface);
	}
	.sentiment-loading {
		padding: 12px;
		color: var(--ii-text-muted);
		font-size: 10px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.sentiment-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
		padding: 0 12px 12px;
	}
	.sentiment-tile {
		display: grid;
		grid-template-columns: 1fr 74px;
		grid-template-rows: auto auto auto;
		align-items: center;
		min-width: 0;
		padding: 8px 10px;
		border: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.sentiment-tile:hover {
		border-color: var(--ii-brand-primary);
	}
	.sentiment-name {
		color: var(--ii-text-muted);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.sentiment-value {
		color: var(--ii-text-primary);
		font-size: 16px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.sentiment-tile .up {
		color: var(--ii-success);
	}
	.sentiment-tile .down {
		color: var(--ii-danger);
	}
	.sentiment-tile span:last-of-type {
		font-size: 9px;
		font-variant-numeric: tabular-nums;
	}
	.sentiment-tile svg {
		grid-column: 2;
		grid-row: 1 / span 3;
		width: 74px;
		height: 26px;
	}
	:global(.lc-cage--standard:has([data-macro-root])) {
		padding: 0 !important;
	}
</style>
