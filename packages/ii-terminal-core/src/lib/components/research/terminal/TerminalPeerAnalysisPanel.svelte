<script lang="ts">
	import { getContext } from "svelte";
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatCompact, formatNumber, formatPercent } from "@investintell/ui";
	import { terminalChartTokens } from "./terminal-chart-tokens";

	interface Props {
		fundId: string | null;
		ticker: string | null;
		label?: string;
	}

	interface Peer {
		external_id: string;
		name: string;
		ticker?: string | null;
		strategy_label?: string | null;
		aum_usd?: number | null;
		expense_ratio_pct?: number | null;
		volatility_1y: number | null;
		sharpe_1y: number | null;
		max_drawdown_1y?: number | null;
		cvar_95?: number | null;
		is_subject: boolean;
	}

	interface PeerPayload {
		peers: Peer[];
		subject: Peer | null;
	}

	interface Institution {
		institution_id: string;
		name: string;
		category: string;
		total_overlap?: number;
		total_value?: number;
	}

	interface RevealHolding {
		cusip: string;
		issuer_name: string;
		pct_of_nav?: number;
	}

	interface RevealPayload {
		institutions: Institution[];
		overlap_matrix: Record<string, Record<string, number>>;
		holdings: RevealHolding[];
	}

	let { fundId, ticker, label = "—" }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	let peerData = $state<PeerPayload | null>(null);
	let revealData = $state<RevealPayload | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	function percent(value: number | null | undefined, digits = 1): string {
		if (value == null) return "—";
		return formatPercent(Math.abs(value) > 1 ? value / 100 : value, digits);
	}

	function truncate(value: string, max: number): string {
		return value.length > max ? `${value.slice(0, max - 1)}…` : value;
	}

	function cleanLabel(value: string | null | undefined): string {
		if (!value) return "—";
		const normalized = value
			.replace(/[_/]+/g, " ")
			.replace(/\s+/g, " ")
			.trim();
		if (!normalized) return "—";
		const tokenMap: Record<string, string> = {
			ETF: "ETF",
			ADR: "ADR",
			REIT: "REIT",
			UCITS: "UCITS",
			NAV: "NAV",
			AUM: "AUM",
			CIK: "CIK",
			"13F": "13F",
			USA: "US",
			US: "US",
			EMEA: "EMEA",
			APAC: "APAC",
		};
		return normalized
			.split(" ")
			.map((word) => {
				const upper = word.toUpperCase();
				if (tokenMap[upper]) return tokenMap[upper];
				if (/^[A-Z0-9-]{2,}$/.test(word)) return upper;
				return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
			})
			.join(" ");
	}

	$effect(() => {
		const id = fundId;
		if (!id) {
			peerData = null;
			revealData = null;
			error = null;
			loading = false;
			return;
		}

		let cancelled = false;
		const controller = new AbortController();
		loading = true;
		error = null;

		(async () => {
			try {
				const token = await getToken();
				const headers = { Authorization: `Bearer ${token}` };
				const [peersResponse, revealResponse] = await Promise.all([
					fetch(`${apiBase}/wealth/discovery/funds/${encodeURIComponent(id)}/analysis/peers`, {
						headers,
						signal: controller.signal,
					}),
					fetch(
						`${apiBase}/wealth/discovery/funds/${encodeURIComponent(id)}/analysis/institutional-reveal`,
						{
							headers,
							signal: controller.signal,
						},
					).catch(() => null),
				]);
				if (!peersResponse.ok) {
					throw new Error(`Peer analysis fetch failed: HTTP ${peersResponse.status}`);
				}
				const peersPayload = (await peersResponse.json()) as PeerPayload;
				const revealPayload =
					revealResponse && revealResponse.ok ? ((await revealResponse.json()) as RevealPayload) : null;
				if (cancelled) return;
				peerData = peersPayload;
				revealData = revealPayload;
			} catch (fetchError: unknown) {
				if (cancelled) return;
				if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
				error = fetchError instanceof Error ? fetchError.message : "Failed to load peer analysis.";
				peerData = null;
				revealData = null;
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		return () => {
			cancelled = true;
			controller.abort();
		};
	});

	const tokens = $derived.by(() => terminalChartTokens());

	const rankedPeers = $derived.by(() =>
		[...(peerData?.peers ?? [])]
			.filter((peer) => peer.sharpe_1y != null)
			.sort((left, right) => (right.sharpe_1y ?? -Infinity) - (left.sharpe_1y ?? -Infinity))
			.slice(0, 14),
	);

	const scatterOption = $derived.by(() => ({
		textStyle: { fontFamily: tokens.font, fontSize: 10 },
			tooltip: {
				backgroundColor: tokens.bg,
				borderColor: tokens.grid,
				borderWidth: 1,
				textStyle: { color: tokens.text, fontSize: 10 },
				formatter: (params: { data: { name: string; ticker: string | null; value: [number, number]; isSubject: boolean } }) => {
					const suffix = params.data.isSubject ? " · SUBJECT" : "";
					const tickerLabel = params.data.ticker ? ` · ${params.data.ticker}` : "";
					return `<strong>${cleanLabel(params.data.name)}</strong>${tickerLabel}${suffix}<br/>VOL ${percent(params.data.value[0], 1)}<br/>SHARPE ${formatNumber(params.data.value[1], 2)}`;
				},
			},
		grid: { left: 48, right: 20, top: 18, bottom: 38, containLabel: true },
		xAxis: {
			type: "value",
			name: "VOL",
			nameGap: 18,
			nameTextStyle: { color: tokens.muted, fontSize: 9 },
			axisLabel: { color: tokens.muted, formatter: (value: number) => percent(value, 0) },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		yAxis: {
			type: "value",
			name: "SHARPE",
			nameGap: 26,
			nameTextStyle: { color: tokens.muted, fontSize: 9 },
			axisLabel: { color: tokens.muted },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		series: [
			{
				type: "scatter",
				data: (peerData?.peers ?? [])
					.filter((peer) => peer.volatility_1y != null && peer.sharpe_1y != null)
					.map((peer) => ({
						value: [peer.volatility_1y as number, peer.sharpe_1y as number],
						name: cleanLabel(peer.name),
						ticker: peer.ticker ?? null,
						isSubject: peer.is_subject,
						symbolSize: peer.is_subject ? 22 : 12,
						itemStyle: {
							color: peer.is_subject ? tokens.amber : tokens.cyan,
							borderColor: peer.is_subject ? tokens.text : tokens.grid,
							borderWidth: peer.is_subject ? 2 : 1,
						},
					})),
			},
		],
	}));

	const matrixHoldings = $derived.by(() => (revealData?.holdings ?? []).slice(0, 10));
	const matrixInstitutions = $derived.by(() => (revealData?.institutions ?? []).slice(0, 8));

	const matrixOption = $derived.by(() => {
		const points: Array<[number, number, number]> = [];
		matrixInstitutions.forEach((institution, y) => {
			matrixHoldings.forEach((holding, x) => {
				const rawValue = revealData?.overlap_matrix?.[institution.institution_id]?.[holding.cusip] ?? 0;
				points.push([x, y, rawValue > 0 ? Math.log10(rawValue + 1) : 0]);
			});
		});
		const maxValue = Math.max(...points.map((point) => point[2]), 1);
		return {
			textStyle: { fontFamily: tokens.font, fontSize: 10 },
			tooltip: {
				backgroundColor: tokens.bg,
				borderColor: tokens.grid,
				borderWidth: 1,
				textStyle: { color: tokens.text, fontSize: 10 },
				formatter: (params: { data: [number, number, number] }) => {
					const holding = matrixHoldings[params.data[0]];
					const institution = matrixInstitutions[params.data[1]];
					if (!holding || !institution) return "";
					const value = revealData?.overlap_matrix?.[institution.institution_id]?.[holding.cusip] ?? 0;
					return `<strong>${cleanLabel(institution.name)}</strong><br/>${cleanLabel(holding.issuer_name)}<br/>${value > 0 ? formatCompact(value) : "No overlap"}`;
				},
			},
			grid: { left: 128, right: 18, top: 18, bottom: 82 },
			xAxis: {
				type: "category",
				data: matrixHoldings.map((holding) => truncate(cleanLabel(holding.issuer_name), 16)),
				axisLabel: { color: tokens.muted, rotate: 35, interval: 0, fontSize: 9 },
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			yAxis: {
				type: "category",
				data: matrixInstitutions.map((institution) => truncate(cleanLabel(institution.name), 22)),
				axisLabel: { color: tokens.muted, fontSize: 9 },
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			visualMap: {
				min: 0,
				max: maxValue,
				show: false,
				inRange: { color: [tokens.panel, tokens.violet, tokens.amber] },
			},
			series: [
				{
					type: "heatmap",
					data: points,
					itemStyle: { borderColor: tokens.grid, borderWidth: 1 },
				},
			],
		};
	});
</script>

<div class="pa-root">
	<div class="pa-header">
		<div class="pa-title-block">
			<div class="pa-title">PEER ANALYSIS</div>
			<div class="pa-subtitle">{ticker ?? "—"} · {cleanLabel(label)}</div>
		</div>
		{#if peerData?.subject}
			<div class="pa-chip">{cleanLabel(peerData.subject.strategy_label ?? "STRATEGY UNSET")}</div>
		{/if}
	</div>

	{#if loading}
		<div class="pa-message">Loading peer analysis...</div>
	{:else if error}
		<div class="pa-message pa-message--error">{error}</div>
	{:else if !peerData || peerData.peers.length === 0}
		<div class="pa-message">No comparable peers with valid risk metrics were found for this fund.</div>
	{:else}
		<div class="pa-grid">
			<section class="pa-panel">
				<div class="pa-panel-head">
					<span>RISK / RETURN MAP</span>
					<span>{peerData.peers.length} PEERS</span>
				</div>
				<div class="pa-chart">
					<ChartContainer option={scatterOption} height={320} ariaLabel="Peer scatter chart" />
				</div>
			</section>

			<section class="pa-panel pa-panel--rank">
				<div class="pa-panel-head">
					<span>SHARPE LADDER</span>
					<span>TOP 14</span>
				</div>
				<div class="pa-rank-list">
					{#each rankedPeers as peer, index (peer.external_id)}
						<div class={`pa-rank-row ${peer.is_subject ? "is-subject" : ""}`}>
							<span class="pa-rank-pos">{index + 1}</span>
							<div class="pa-rank-meta">
								<strong>{peer.ticker ?? "—"}</strong>
								<span>{truncate(cleanLabel(peer.name), 28)}</span>
							</div>
							<span>{peer.sharpe_1y != null ? formatNumber(peer.sharpe_1y, 2) : "—"}</span>
							<span>{percent(peer.max_drawdown_1y, 1)}</span>
						</div>
					{/each}
				</div>
			</section>

			<section class="pa-panel pa-panel--wide">
				<div class="pa-panel-head">
					<span>MANAGER ALLOCATION REVEAL</span>
					<span>{matrixInstitutions.length} INSTITUTIONS × {matrixHoldings.length} HOLDINGS</span>
				</div>
				{#if matrixInstitutions.length > 0 && matrixHoldings.length > 0}
					<div class="pa-matrix">
						<ChartContainer option={matrixOption} height={340} ariaLabel="Institutional reveal matrix" />
					</div>
				{:else}
					<div class="pa-message">Curated institutional overlap is not available yet for this fund.</div>
				{/if}
			</section>
		</div>
	{/if}
</div>

<style>
	.pa-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-width: 0;
		min-height: 0;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.pa-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
		padding: 10px 12px 8px;
		border-bottom: var(--terminal-border-hairline);
	}

	.pa-title-block {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}

	.pa-title,
	.pa-panel-head span:first-child {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
	}

	.pa-subtitle,
	.pa-panel-head span:last-child,
	.pa-chip,
	.pa-rank-row span,
	.pa-rank-meta span {
		color: var(--terminal-fg-muted);
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		font-variant-numeric: tabular-nums;
	}

	.pa-chip {
		padding: 3px 8px;
		border: 1px solid var(--terminal-accent-cyan-dim);
		color: var(--terminal-accent-cyan);
	}

	.pa-message {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		padding: 24px;
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
		text-align: center;
	}

	.pa-message--error {
		color: var(--terminal-status-error);
	}

	.pa-grid {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1.4fr) minmax(340px, 0.8fr);
		grid-template-rows: minmax(0, 0.95fr) minmax(0, 1.05fr);
		gap: 1px;
		background: var(--terminal-fg-disabled);
	}

	.pa-panel {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		background: var(--terminal-bg-panel);
	}

	.pa-panel--wide {
		grid-column: 1 / -1;
	}

	.pa-panel-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 8px 10px 6px;
		border-bottom: var(--terminal-border-hairline);
	}

	.pa-chart,
	.pa-matrix {
		flex: 1;
		min-height: 0;
		padding: 8px 10px 10px;
	}

	.pa-rank-list {
		display: flex;
		flex-direction: column;
		overflow: auto;
	}

	.pa-rank-row {
		display: grid;
		grid-template-columns: 30px minmax(0, 1fr) 56px 62px;
		gap: 10px;
		align-items: center;
		padding: 8px 10px;
		border-bottom: 1px solid var(--terminal-fg-disabled);
	}

	.pa-rank-row.is-subject {
		background: color-mix(in srgb, var(--terminal-accent-amber) 10%, transparent);
	}

	.pa-rank-pos {
		color: var(--terminal-fg-secondary);
	}

	.pa-rank-meta {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.pa-rank-meta strong {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-12);
	}

	@media (max-width: 1280px) {
		.pa-grid {
			grid-template-columns: 1fr;
			grid-template-rows: minmax(320px, 0.9fr) minmax(280px, 0.7fr) minmax(320px, 1fr);
		}

		.pa-panel--wide {
			grid-column: auto;
		}
	}
</style>
