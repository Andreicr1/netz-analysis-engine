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
		<span class="macro-toolbar-title">MACRO</span>
		<span class="macro-toolbar-regime" class:macro-regime--risk-off={activeRegime.includes("OFF") || activeRegime.includes("RISK")}>
			{activeRegime}
		</span>
		{#if fetchError}
			<span class="macro-toolbar-error">DATA ERROR</span>
		{/if}
	</div>

	<div class="macro-grid">
		<div class="macro-col macro-col--left">
			<CrossAssetPanel assets={crossAssets} loading={crossAssetsLoading} onAssetSelect={(asset) => (focusAsset = asset)} />
		</div>

		<div class="macro-col macro-col--center">
			<div class="macro-center-top">
				<RegimePlot
					{activeRegime}
					{livePin}
					simulatedPin={simStore.simPin}
					trail={trailPoints}
					onSimulate={(pin) => simStore.set(pin)}
				/>
			</div>
			<div class="macro-center-bottom">
				<LiquidityPanel nfci={nfci} history={nfciHistory} loading={liquidityLoading} />
			</div>
		</div>

		<div class="macro-col macro-col--right">
			<CBPanel events={cbEvents} loading={cbLoading} />
			<EconPanel rows={econRows} loading={econLoading} />
			<MacroNewsFeed />
		</div>
	</div>

	<AssetDrawer asset={focusAsset} onClose={() => (focusAsset = null)} fetchSeries={fetchAssetSeries} />
</div>

<style>
	.macro-desk {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 88px);
		overflow: hidden;
		background: var(--terminal-bg-panel-sunken);
		font-family: var(--terminal-font-mono);
	}
	.macro-toolbar {
		display: flex;
		flex-shrink: 0;
		align-items: center;
		gap: var(--terminal-space-3);
		height: 32px;
		padding: 0 var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
	}
	.macro-toolbar-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.macro-toolbar-regime {
		margin-left: auto;
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.macro-toolbar-error,
	.macro-regime--risk-off {
		color: var(--terminal-accent-red, #f87171);
	}
	.macro-toolbar-error {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.macro-grid {
		display: grid;
		flex: 1;
		grid-template-columns: 320px 1fr 300px;
		gap: 1px;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel-sunken);
	}
	.macro-col {
		min-height: 0;
		overflow-y: auto;
		background: var(--terminal-bg-panel);
	}
	.macro-col--center {
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto;
		gap: 1px;
		overflow: hidden;
		background: var(--terminal-bg-panel-sunken);
	}
	.macro-center-top,
	.macro-center-bottom {
		min-height: 0;
		background: var(--terminal-bg-panel);
	}
	.macro-center-top {
		overflow: hidden;
	}
	.macro-center-bottom {
		overflow-y: auto;
	}
	.macro-col--right {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--terminal-bg-panel-sunken);
	}
	.macro-col--right > :global(*) {
		flex-shrink: 0;
	}
</style>
