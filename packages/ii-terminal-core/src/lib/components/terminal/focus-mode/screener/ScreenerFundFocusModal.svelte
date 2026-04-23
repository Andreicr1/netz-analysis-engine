<!--
  ScreenerFundFocusModal -- constrained fund focus for the screener page.

  1040px x 88vh quick-view modal with SVG performance and composite radar.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatCurrency, formatNumber, formatPercent } from "@investintell/ui";
	import { createClientApiClient } from "../../../../api/client";

	interface Props {
		fundId: string;
		fundLabel: string;
		ticker: string | null;
		instrumentId: string | null;
		onClose: () => void;
	}

	let { fundId, fundLabel, ticker, instrumentId, onClose }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface FundCatalogItem {
		name: string;
		manager_name: string | null;
		aum: number | null;
		strategy_label: string | null;
		fund_type: string | null;
		expense_ratio_pct: number | null;
		avg_annual_return_1y: number | null;
		avg_annual_return_10y: number | null;
		manager_score: number | null;
		blended_momentum_score: number | null;
		max_drawdown: number | null;
		sharpe_ratio: number | null;
		volatility: number | null;
	}

	interface NavBar {
		date: string;
		value: number;
	}

	interface Holding {
		issuer_name: string;
		cusip: string | null;
		sector: string | null;
		weight: number | null;
		market_value: number | null;
	}

	interface SectorInfo {
		name: string;
		weight: number | null;
		holdings_count: number | null;
	}

	interface HoldingsData {
		top_holdings: Holding[];
		sector_breakdown: SectorInfo[];
		as_of?: string | null;
		disclosure?: {
			has_holdings?: boolean;
			message?: string | null;
		} | null;
	}

	let detail = $state<FundCatalogItem | null>(null);
	let navBars = $state<NavBar[]>([]);
	let holdingsData = $state<HoldingsData | null>(null);
	let loadingDetail = $state(true);
	let loadingNav = $state(false);
	let loadingHoldings = $state(false);

	$effect(() => {
		const id = fundId;
		let cancelled = false;
		loadingDetail = true;
		api
			.get<FundCatalogItem>(`/screener/catalog/detail/${encodeURIComponent(id)}`)
			.then((res) => {
				if (cancelled) return;
				detail = res ?? null;
				loadingDetail = false;
			})
			.catch(() => {
				if (cancelled) return;
				detail = null;
				loadingDetail = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const symbol = ticker;
		void instrumentId;
		if (!symbol) {
			navBars = [];
			return;
		}
		let cancelled = false;
		loadingNav = true;
		const start = new Date(Date.now() - 365 * 5 * 86_400_000)
			.toISOString()
			.slice(0, 10);
		api
			.get<{ bars: Array<{ timestamp: string; close: number | null }> }>(
				`/market-data/historical/${encodeURIComponent(symbol)}`,
				{ start_date: start },
			)
			.then((res) => {
				if (cancelled) return;
				navBars = (res.bars ?? [])
					.filter((bar) => bar.close != null)
					.map((bar) => ({
						date: bar.timestamp.slice(0, 10),
						value: Number(bar.close),
					}));
				loadingNav = false;
			})
			.catch(() => {
				if (cancelled) return;
				navBars = [];
				loadingNav = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const id = fundId;
		if (!id) {
			holdingsData = null;
			return;
		}
		let cancelled = false;
		loadingHoldings = true;
		api
			.get<HoldingsData>(`/wealth/discovery/funds/${encodeURIComponent(id)}/analysis/holdings/top`)
			.then((res) => {
				if (cancelled) return;
				holdingsData = res ?? null;
				loadingHoldings = false;
			})
			.catch(() => {
				if (cancelled) return;
				holdingsData = null;
				loadingHoldings = false;
			});
		return () => {
			cancelled = true;
		};
	});

	const PERIODS: Array<{ label: string; days: number }> = [
		{ label: "1M", days: 30 },
		{ label: "3M", days: 91 },
		{ label: "6M", days: 182 },
		{ label: "1Y", days: 365 },
		{ label: "3Y", days: 365 * 3 },
		{ label: "5Y", days: 365 * 5 },
	];

	const periodStats = $derived.by(() => {
		if (navBars.length < 2) {
			return PERIODS.map((period) => ({ label: period.label, returnPct: null as number | null }));
		}
		const last = navBars[navBars.length - 1];
		return PERIODS.map((period) => {
			const cutoff = new Date(Date.now() - period.days * 86_400_000)
				.toISOString()
				.slice(0, 10);
			const ref = navBars.find((bar) => bar.date >= cutoff);
			if (!last || !ref || ref.value === 0) {
				return { label: period.label, returnPct: null };
			}
			return {
				label: period.label,
				returnPct: (last.value - ref.value) / ref.value,
			};
		});
	});

	const CHART_W = 640;
	const CHART_H = 220;

	const perfChart = $derived.by(() => {
		if (navBars.length < 2) return { area: "", line: "", isUp: true };
		const values = navBars.map((bar) => bar.value);
		const minValue = Math.min(...values);
		const maxValue = Math.max(...values);
		const range = maxValue - minValue || 1;
		const points = values.map((value, index) => {
			const x = (index / (values.length - 1)) * CHART_W;
			const y = CHART_H - ((value - minValue) / range) * CHART_H;
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		});
		const line = "M " + points.join(" L ");
		return {
			area: `${line} L ${CHART_W},${CHART_H} L 0,${CHART_H} Z`,
			line,
			isUp: values[values.length - 1]! >= values[0]!,
		};
	});

	const AXES = ["RETURN", "MOMENTUM", "RISK ADJ", "DD CTL", "COST EFF", "CONSISTENCY"] as const;
	const RADAR_W = 200;
	const RADAR_H = 160;
	const CX = RADAR_W / 2;
	const CY = RADAR_H / 2;
	const R = 65;
	const N = AXES.length;

	function radarPt(index: number, radius: number) {
		const angle = (index / N) * 2 * Math.PI - Math.PI / 2;
		return {
			x: CX + radius * Math.cos(angle),
			y: CY + radius * Math.sin(angle),
		};
	}

	function clampScore(value: number): number {
		return Math.min(100, Math.max(0, value));
	}

	function asDecimalPercent(value: number | null | undefined): number | null {
		if (value == null) return null;
		return Math.abs(value) > 1 ? value / 100 : value;
	}

	function peerSubjectLeft(
		value: number | null,
		p25: number | null,
		p75: number | null,
		fallbackP25: number,
		fallbackP75: number,
	): string {
		if (value == null) return "0%";
		const low = p25 ?? fallbackP25;
		const high = p75 ?? fallbackP75;
		const range = high - low || Math.abs(fallbackP75 - fallbackP25) || 1;
		const pct = Math.max(0, Math.min(100, ((value - low) / range) * 100));
		return `${pct}%`;
	}

	const axisScores = $derived.by((): number[] => {
		if (!detail) return Array(N).fill(50);
		const returnDecimal = asDecimalPercent(detail.avg_annual_return_1y);
		const drawdownDecimal = asDecimalPercent(detail.max_drawdown);
		const expensePct = detail.expense_ratio_pct ?? null;
		return [
			returnDecimal != null ? clampScore((returnDecimal + 0.1) * 500) : 50,
			detail.blended_momentum_score ?? 50,
			detail.sharpe_ratio != null ? clampScore((detail.sharpe_ratio + 0.5) * 50) : 50,
			drawdownDecimal != null ? clampScore((1 + drawdownDecimal / 0.5) * 100) : 50,
			expensePct != null ? clampScore(100 - expensePct * 50) : 50,
			detail.manager_score ?? 50,
		];
	});

	const radarPath = $derived.by(() => {
		const points = axisScores.map((score, index) => {
			const p = radarPt(index, (score / 100) * R);
			return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
		});
		return "M " + points.join(" L ") + " Z";
	});

	const w52 = $derived.by(() => {
		const cutoff = new Date(Date.now() - 365 * 86_400_000).toISOString().slice(0, 10);
		const values = navBars.filter((bar) => bar.date >= cutoff).map((bar) => bar.value);
		if (values.length === 0) return null;
		return { high: Math.max(...values), low: Math.min(...values) };
	});

	interface PeerMetricsResponse {
		strategy_label: string | null;
		peer_count: number;
		subject_sharpe: number | null;
		subject_drawdown: number | null;
		peer_sharpe_p25: number | null;
		peer_sharpe_p50: number | null;
		peer_sharpe_p75: number | null;
		peer_drawdown_p25: number | null;
		peer_drawdown_p50: number | null;
		peer_drawdown_p75: number | null;
		top_peers: Array<{
			ticker: string;
			name: string;
			sharpe_ratio: number | null;
			max_drawdown: number | null;
		}>;
	}

	interface DDReportSummary {
		id: string;
		version: number;
		status: string;
		confidence_score: number | null;
		decision_anchor: string | null;
		is_current: boolean;
		created_at: string;
	}

	interface ReverseLookupHolder {
		cik: string;
		firm_name: string;
		shares: number | null;
		market_value: number | null;
		pct_of_total: number | null;
		report_date: string;
	}

	interface ReverseLookupResponse {
		cusip: string;
		company_name: string | null;
		holders: ReverseLookupHolder[];
		total_holders: number;
	}

	interface HoldingsHistoryPoint {
		quarter: string;
		total_holders: number;
		total_market_value: number;
	}

	interface HoldingsHistoryResponse {
		cusip: string;
		quarters: HoldingsHistoryPoint[];
	}

	interface ManagerDetailResponse {
		crd_number: string;
		cik: string | null;
		firm_name: string;
		registration_status: string | null;
		aum_total: number | null;
		state: string | null;
		country: string | null;
		latest_quarter: string | null;
		holdings_count: number;
		total_portfolio_value: number | null;
		private_fund_count: number | null;
		hedge_fund_count: number | null;
		pe_fund_count: number | null;
		vc_fund_count: number | null;
		total_private_fund_assets: number | null;
	}

	let peerMetrics = $state<PeerMetricsResponse | null>(null);
	let loadingPeer = $state(false);
	let ddReports = $state<DDReportSummary[]>([]);
	let loadingDD = $state(false);
	let focusTab = $state<"performance" | "profile" | "analysis" | "holdings" | "sectors">("performance");
	let selectedSector = $state<string | null>(null);
	let selectedHolding = $state<string | null>(null);
	let sectorTreemapChart = $state<any>();
	let holdingsBarChart = $state<any>();
	let selectedHoldingCusip = $state<string | null>(null);
	let reverseLookup = $state<ReverseLookupResponse | null>(null);
	let loadingReverseLookup = $state(false);
	let holdingHistory = $state<HoldingsHistoryResponse | null>(null);
	let loadingHoldingHistory = $state(false);
	let activeHolderCik = $state<string | null>(null);
	let activeHolderManager = $state<ManagerDetailResponse | null>(null);
	let loadingActiveHolderManager = $state(false);

	const topHoldings = $derived(holdingsData?.top_holdings ?? []);
	const displayedHoldings = $derived.by(() =>
		selectedSector
			? topHoldings.filter((holding) => (holding.sector ?? "Unclassified") === selectedSector)
			: topHoldings,
	);
	const sectorBreakdown = $derived.by(() =>
		[...(holdingsData?.sector_breakdown ?? [])].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)),
	);

	$effect(() => {
		if (selectedSector && !topHoldings.some((holding) => (holding.sector ?? "Unclassified") === selectedSector)) {
			selectedSector = null;
			selectedHolding = null;
			selectedHoldingCusip = null;
		}
	});

	$effect(() => {
		if (!selectedHoldingCusip) {
			reverseLookup = null;
			loadingReverseLookup = false;
			return;
		}
		let cancelled = false;
		loadingReverseLookup = true;
		api
			.get<ReverseLookupResponse>("/sec/holdings/reverse", {
				cusip: selectedHoldingCusip,
				limit: 6,
			})
			.then((res) => {
				if (cancelled) return;
				reverseLookup = res ?? null;
				loadingReverseLookup = false;
			})
			.catch(() => {
				if (cancelled) return;
				reverseLookup = null;
				loadingReverseLookup = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		if (!selectedHoldingCusip) {
			holdingHistory = null;
			loadingHoldingHistory = false;
			return;
		}
		let cancelled = false;
		loadingHoldingHistory = true;
		api
			.get<HoldingsHistoryResponse>("/sec/holdings/history", {
				cusip: selectedHoldingCusip,
			})
			.then((res) => {
				if (cancelled) return;
				holdingHistory = res ?? null;
				loadingHoldingHistory = false;
			})
			.catch(() => {
				if (cancelled) return;
				holdingHistory = null;
				loadingHoldingHistory = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const holders = reverseLookup?.holders ?? [];
		if (holders.length === 0) {
			activeHolderCik = null;
			return;
		}
		if (!activeHolderCik || !holders.some((holder) => holder.cik === activeHolderCik)) {
			activeHolderCik = holders[0]?.cik ?? null;
		}
	});

	$effect(() => {
		if (!activeHolderCik) {
			activeHolderManager = null;
			loadingActiveHolderManager = false;
			return;
		}
		let cancelled = false;
		loadingActiveHolderManager = true;
		api
			.get<ManagerDetailResponse>(`/sec/managers/${encodeURIComponent(activeHolderCik)}`)
			.then((res) => {
				if (cancelled) return;
				activeHolderManager = res ?? null;
				loadingActiveHolderManager = false;
			})
			.catch(() => {
				if (cancelled) return;
				activeHolderManager = null;
				loadingActiveHolderManager = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const id = fundId;
		if (!id) return;
		let cancelled = false;
		loadingPeer = true;
		api
			.get<PeerMetricsResponse>(`/screener/peer-metrics/${encodeURIComponent(id)}`)
			.then((res) => {
				if (cancelled) return;
				peerMetrics = res;
				loadingPeer = false;
			})
			.catch(() => {
				if (cancelled) return;
				peerMetrics = null;
				loadingPeer = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const iid = instrumentId;
		if (!iid) {
			ddReports = [];
			return;
		}
		let cancelled = false;
		loadingDD = true;
		api
			.get<DDReportSummary[]>(`/dd-reports/funds/${encodeURIComponent(iid)}`)
			.then((res) => {
				if (cancelled) return;
				ddReports = res ?? [];
				loadingDD = false;
			})
			.catch(() => {
				if (cancelled) return;
				ddReports = [];
				loadingDD = false;
			});
		return () => {
			cancelled = true;
		};
	});

	function percentText(value: number | null | undefined, decimals = 2): string {
		const decimal = asDecimalPercent(value);
		return decimal == null ? "\u2014" : formatPercent(decimal, decimals);
	}

	function holdingWeightText(value: number | null | undefined): string {
		if (value == null) return "\u2014";
		const decimal = Math.abs(value) > 1 ? value / 100 : value;
		return formatPercent(decimal, 2);
	}

	function pctValue(value: number | null | undefined): number {
		if (value == null) return 0;
		return Math.abs(value) > 1 ? Math.max(0, value) : Math.max(0, value * 100);
	}

	function moneyText(value: number | null | undefined): string {
		if (value == null) return "\u2014";
		const abs = Math.abs(value);
		if (abs >= 1_000_000_000) return `$${formatNumber(value / 1_000_000_000, 2)}B`;
		if (abs >= 1_000_000) return `$${formatNumber(value / 1_000_000, 1)}M`;
		return formatCurrency(value);
	}

	function closeOnEscape(event: KeyboardEvent) {
		if (event.key === "Escape") onClose();
	}

	function openResearch(mode: "fund" | "holdings" = "fund") {
		const params = new URLSearchParams({
			fund: fundId,
			mode,
		});
		onClose();
		goto(`${base}/screener/research?${params.toString()}`);
	}

	onMount(() => {
		document.addEventListener("keydown", closeOnEscape);
		return () => document.removeEventListener("keydown", closeOnEscape);
	});

	const SECTOR_COLORS = [
		"#5975D9",
		"#B7D82D",
		"#596081",
		"#FF9A4D",
		"#1FA5D6",
		"#FFD02A",
		"#7D60C7",
		"#47BE95",
		"#F15C8A",
		"#8F9BBC",
	];

	function withAlpha(hex: string, alpha: number): string {
		const normalized = hex.replace("#", "");
		if (normalized.length !== 6) return hex;
		const r = Number.parseInt(normalized.slice(0, 2), 16);
		const g = Number.parseInt(normalized.slice(2, 4), 16);
		const b = Number.parseInt(normalized.slice(4, 6), 16);
		return `rgba(${r}, ${g}, ${b}, ${alpha})`;
	}

	const treemapData = $derived.by(() => {
		const sectorWeights = new Map(
			sectorBreakdown.map((sector) => [sector.name || "Unclassified", pctValue(sector.weight)]),
		);
		const sectorCounts = new Map(
			sectorBreakdown.map((sector) => [sector.name || "Unclassified", sector.holdings_count ?? 0]),
		);
		const grouped = new Map<string, Holding[]>();
		for (const holding of topHoldings) {
			const sectorName = holding.sector || "Unclassified";
			const bucket = grouped.get(sectorName) ?? [];
			bucket.push(holding);
			grouped.set(sectorName, bucket);
		}

		return Array.from(new Set<string>([...sectorWeights.keys(), ...grouped.keys()]))
			.map((name, index) => {
				const color = SECTOR_COLORS[index % SECTOR_COLORS.length] ?? "#5975D9";
				const children = [...(grouped.get(name) ?? [])]
					.sort((a, b) => pctValue(b.weight) - pctValue(a.weight))
					.map((holding) => ({
						name: holding.issuer_name,
						cusip: holding.cusip ?? null,
						value: pctValue(holding.weight),
						weightPct: pctValue(holding.weight),
						marketValue: holding.market_value ?? null,
						itemStyle: {
							color: withAlpha(color, 0.78),
							borderColor: withAlpha(color, 0.92),
							gapWidth: 1,
						},
					}));
				const sectorWeight = sectorWeights.get(name) ?? children.reduce((sum, child) => sum + child.value, 0);
				const knownWeight = children.reduce((sum, child) => sum + child.value, 0);
				const remainder = Math.max(0, sectorWeight - knownWeight);
				if (remainder >= 0.15) {
					children.push({
						name: "Other positions",
						cusip: null,
						value: remainder,
						weightPct: remainder,
						marketValue: null,
						itemStyle: {
							color: withAlpha(color, 0.34),
							borderColor: withAlpha(color, 0.5),
							gapWidth: 1,
						},
					});
				}

				return {
					name,
					value: sectorWeight,
					weightPct: sectorWeight,
					holdingsCount: sectorCounts.get(name) ?? children.length,
					itemStyle: {
						color,
						borderColor: withAlpha(color, 0.92),
						gapWidth: 2,
					},
					children,
				};
			})
			.sort((a, b) => (b.weightPct ?? 0) - (a.weightPct ?? 0));
	});

	const sectorTreemapOption = $derived.by(
		() =>
			({
				backgroundColor: "transparent",
				animationDurationUpdate: 420,
				tooltip: {
					backgroundColor: "rgba(11, 18, 48, 0.96)",
					borderColor: "rgba(102, 137, 188, 0.28)",
					borderWidth: 1,
					textStyle: { color: "#E8EEF9", fontSize: 10, fontFamily: "var(--ii-font-mono)" },
					formatter: (params: {
						name: string;
						treePathInfo?: Array<{ name: string }>;
						data?: { weightPct?: number; holdingsCount?: number; marketValue?: number | null };
					}) => {
						const path = (params.treePathInfo ?? [])
							.map((node) => node.name)
							.filter(Boolean)
							.slice(1);
						const weight = params.data?.weightPct != null ? holdingWeightText(params.data.weightPct) : "\u2014";
						const mv =
							params.data?.marketValue != null
								? `<br/>Value ${moneyText(params.data.marketValue)}`
								: "";
						const count =
							params.data?.holdingsCount != null ? `<br/>${params.data.holdingsCount} holdings` : "";
						return `<strong>${params.name}</strong><br/>${path.join(" / ") || "Portfolio"}<br/>Weight ${weight}${count}${mv}`;
					},
				},
				series: [
					{
						type: "treemap",
						data: treemapData,
						nodeClick: "zoomToNode",
						breadcrumb: {
							show: true,
							height: 22,
							itemStyle: {
								color: "rgba(15, 24, 61, 0.9)",
								borderColor: "rgba(102, 137, 188, 0.26)",
							},
							emphasis: {
								itemStyle: {
									color: "rgba(255, 150, 90, 0.18)",
								},
							},
							textStyle: {
								color: "#9AA9D4",
								fontSize: 9,
								fontFamily: "var(--ii-font-mono)",
							},
						},
						label: {
							show: true,
							color: "#F3F6FF",
							fontSize: 11,
							formatter: (params: { name: string; data?: { weightPct?: number } }) => {
								const weight = params.data?.weightPct != null ? holdingWeightText(params.data.weightPct) : "";
								return weight ? `${params.name}\n${weight}` : params.name;
							},
							overflow: "truncate",
						},
						upperLabel: {
							show: true,
							height: 20,
							color: "#F3F6FF",
							fontSize: 11,
							fontWeight: 700,
							overflow: "truncate",
						},
						itemStyle: {
							borderColor: "rgba(11, 18, 48, 0.95)",
							borderWidth: 1,
							gapWidth: 2,
						},
						roam: false,
						visibleMin: 0.12,
						leafDepth: 1,
						universalTransition: true,
						levels: [
							{
								itemStyle: {
									borderColor: "rgba(11, 18, 48, 0.95)",
									borderWidth: 1,
									gapWidth: 3,
								},
								upperLabel: { show: true },
							},
							{
								itemStyle: {
									borderColor: "rgba(11, 18, 48, 0.9)",
									borderWidth: 1,
									gapWidth: 1,
								},
							},
						],
					},
				],
			}) as Record<string, unknown>,
	);

	const holdingsStats = $derived.by(() => {
		const weights = displayedHoldings.map((holding) => pctValue(holding.weight));
		const sum = (count: number) => weights.slice(0, count).reduce((acc, value) => acc + value, 0);
		return {
			top3: sum(3),
			top5: sum(5),
			top10: sum(10),
			positions: displayedHoldings.length,
		};
	});

	const holdingsMaxWeight = $derived.by(() =>
		displayedHoldings.reduce((max, holding) => Math.max(max, pctValue(holding.weight)), 0),
	);

	const holdingsSectorMix = $derived.by(() => {
		const grouped = new Map<string, { name: string; weight: number; count: number; color: string }>();
		for (const holding of displayedHoldings) {
			const name = holding.sector ?? "Unclassified";
			const current = grouped.get(name);
			if (current) {
				current.weight += pctValue(holding.weight);
				current.count += 1;
				continue;
			}
			const colorIndex = grouped.size % SECTOR_COLORS.length;
			grouped.set(name, {
				name,
				weight: pctValue(holding.weight),
				count: 1,
				color: SECTOR_COLORS[colorIndex] ?? "#5975D9",
			});
		}
		return [...grouped.values()].sort((a, b) => b.weight - a.weight);
	});

	const disclosedTopWeight = $derived.by(() =>
		holdingsSectorMix.reduce((sum, sector) => sum + sector.weight, 0),
	);

	const activeSectorSummary = $derived.by(() => {
		if (!selectedSector) return null;
		const sectorInfo =
			sectorBreakdown.find((sector) => (sector.name || "Unclassified") === selectedSector) ?? null;
		const holdings = topHoldings
			.filter((holding) => (holding.sector ?? "Unclassified") === selectedSector)
			.sort((a, b) => pctValue(b.weight) - pctValue(a.weight));
		const disclosedWeight = holdings.reduce((sum, holding) => sum + pctValue(holding.weight), 0);
		return {
			name: selectedSector,
			totalWeight: sectorInfo?.weight ?? disclosedWeight,
			holdingsCount: sectorInfo?.holdings_count ?? holdings.length,
			disclosedWeight,
			topNames: holdings.slice(0, 4),
		};
	});

	const selectedHoldingData = $derived.by(
		() =>
			displayedHoldings.find(
				(holding) =>
					(selectedHoldingCusip && holding.cusip === selectedHoldingCusip) ||
					(selectedHolding && holding.issuer_name === selectedHolding),
			) ?? null,
	);

	const activeHolder = $derived.by(
		() => reverseLookup?.holders.find((holder) => holder.cik === activeHolderCik) ?? null,
	);

	function relativeWeightWidth(value: number | null | undefined): string {
		const max = holdingsMaxWeight || 0;
		if (max <= 0) return "0%";
		return `${Math.max(8, Math.min(100, (pctValue(value) / max) * 100)).toFixed(1)}%`;
	}

	function sectorMixWidth(value: number): string {
		const total = disclosedTopWeight || 0;
		if (total <= 0) return "0%";
		return `${Math.max(4, Math.min(100, (value / total) * 100)).toFixed(1)}%`;
	}

	const holdingsHistoryOption = $derived.by(() => {
		const points = holdingHistory?.quarters ?? [];
		return {
			backgroundColor: "transparent",
			grid: { left: 42, right: 16, top: 18, bottom: 28 },
			tooltip: {
				trigger: "axis",
				backgroundColor: "rgba(11, 18, 48, 0.96)",
				borderColor: "rgba(102, 137, 188, 0.28)",
				borderWidth: 1,
				textStyle: { color: "#E8EEF9", fontSize: 10, fontFamily: "var(--ii-font-mono)" },
			},
			xAxis: {
				type: "category",
				data: points.map((point) => point.quarter.slice(0, 7)),
				axisLabel: {
					color: "var(--ii-text-muted, var(--terminal-fg-muted))",
					fontSize: 9,
				},
				axisLine: { lineStyle: { color: "rgba(102, 137, 188, 0.2)" } },
			},
			yAxis: [
				{
					type: "value",
					name: "Holders",
					nameTextStyle: {
						color: "var(--ii-text-muted, var(--terminal-fg-muted))",
						fontSize: 9,
						fontFamily: "var(--ii-font-mono)",
					},
					axisLabel: {
						color: "var(--ii-text-muted, var(--terminal-fg-muted))",
						fontSize: 9,
					},
					splitLine: { lineStyle: { color: "rgba(102, 137, 188, 0.12)", type: "dashed" } },
				},
				{
					type: "value",
					name: "Value",
					nameTextStyle: {
						color: "var(--ii-text-muted, var(--terminal-fg-muted))",
						fontSize: 9,
						fontFamily: "var(--ii-font-mono)",
					},
					axisLabel: {
						color: "var(--ii-text-muted, var(--terminal-fg-muted))",
						fontSize: 9,
						formatter: (value: number) => moneyText(value),
					},
					splitLine: { show: false },
				},
			],
			series: [
				{
					name: "Holders",
					type: "line",
					smooth: true,
					data: points.map((point) => point.total_holders),
					symbolSize: 6,
					lineStyle: { width: 2, color: "#FF9A4D" },
					itemStyle: { color: "#FFB36C" },
					areaStyle: { color: "rgba(255, 154, 77, 0.12)" },
				},
				{
					name: "Market Value",
					type: "bar",
					yAxisIndex: 1,
					barWidth: 14,
					data: points.map((point) => point.total_market_value),
					itemStyle: {
						color: "rgba(61, 211, 154, 0.35)",
						borderColor: "rgba(61, 211, 154, 0.85)",
						borderWidth: 1,
						borderRadius: [2, 2, 0, 0],
					},
				},
			],
		} as Record<string, unknown>;
	});

	const holdingsBarOption = $derived.by(() => {
		const rows = displayedHoldings
			.slice(0, 10)
			.map((holding) => ({
				name: holding.issuer_name,
				sector: holding.sector ?? "—",
				value: pctValue(holding.weight),
				marketValue: holding.market_value ?? null,
				cusip: holding.cusip ?? null,
				isSelected:
					(selectedHoldingCusip && holding.cusip === selectedHoldingCusip) ||
					selectedHolding === holding.issuer_name,
			}))
			.sort((a, b) => a.value - b.value);

		return {
			backgroundColor: "transparent",
			grid: { left: 200, right: 24, top: 12, bottom: 20, containLabel: false },
			xAxis: {
				type: "value",
				axisLabel: {
					color: "var(--ii-text-muted, var(--terminal-fg-muted))",
					formatter: (value: number) => holdingWeightText(value),
				},
				splitLine: {
					lineStyle: { color: "rgba(102, 137, 188, 0.14)", type: "dashed" },
				},
				axisLine: { lineStyle: { color: "var(--ii-border-subtle, var(--terminal-fg-muted))" } },
			},
			yAxis: {
				type: "category",
				data: rows.map((row) => row.name.length > 28 ? `${row.name.slice(0, 27)}…` : row.name),
				axisTick: { show: false },
				axisLine: { show: false },
				axisLabel: {
					color: "var(--ii-text-primary, var(--terminal-fg-primary))",
					fontSize: 10,
					margin: 14,
				},
			},
			tooltip: {
				backgroundColor: "rgba(11, 18, 48, 0.96)",
				borderColor: "rgba(102, 137, 188, 0.28)",
				borderWidth: 1,
				textStyle: { color: "#E8EEF9", fontSize: 10, fontFamily: "var(--ii-font-mono)" },
				formatter: (params: { data?: { name: string; sector: string; value: number; marketValue: number | null } }) => {
					const data = params.data;
					if (!data) return "";
					return `<strong>${data.name}</strong><br/>${data.sector}<br/>Weight ${holdingWeightText(data.value)}<br/>Value ${moneyText(data.marketValue)}`;
				},
			},
			series: [
				{
					type: "bar",
					data: rows,
					barWidth: 16,
					showBackground: true,
					backgroundStyle: {
						color: "rgba(102, 137, 188, 0.08)",
					},
					label: {
						show: true,
						position: "right",
						color: "var(--ii-text-primary, var(--terminal-fg-primary))",
						fontSize: 10,
						formatter: (params: { data?: { value: number } }) =>
							params.data?.value != null ? holdingWeightText(params.data.value) : "—",
					},
					itemStyle: {
						borderRadius: [0, 3, 3, 0],
					},
					color: (params: { data?: { isSelected?: boolean } }) =>
						params.data?.isSelected
							? "#FFB36C"
							: {
									type: "linear",
									x: 0,
									y: 0,
									x2: 1,
									y2: 0,
									colorStops: [
										{ offset: 0, color: "#FF9A4D" },
										{ offset: 1, color: "#3DD39A" },
									],
								},
				},
			],
		} as Record<string, unknown>;
	});

	function clearHoldingsFilter() {
		selectedSector = null;
		selectedHolding = null;
		selectedHoldingCusip = null;
		focusTab = "holdings";
	}

	function focusSector(sectorName: string, targetTab: "holdings" | "sectors" = "sectors") {
		selectedSector = sectorName;
		selectedHolding = null;
		selectedHoldingCusip = null;
		focusTab = targetTab;
	}

	function focusHolding(holding: Holding) {
		selectedHolding = holding.issuer_name;
		selectedHoldingCusip = holding.cusip ?? null;
		if (holding.sector) selectedSector = holding.sector;
		focusTab = "holdings";
	}

	$effect(() => {
		if (!sectorTreemapChart) return;
		const handleClick = (params: any) => {
			const path = (params.treePathInfo ?? [])
				.map((node: { name?: string }) => node.name)
				.filter(Boolean);
			const sectorName = path[1] ?? params.name ?? null;
			const isHoldingNode = path.length >= 3;
			selectedSector = sectorName;
			selectedHolding = isHoldingNode ? (params.name ?? null) : null;
			selectedHoldingCusip = isHoldingNode ? (params.data?.cusip ?? null) : null;
			focusTab = "holdings";
		};
		sectorTreemapChart.off("click");
		sectorTreemapChart.on("click", handleClick);
		return () => {
			sectorTreemapChart?.off("click", handleClick);
		};
	});

	$effect(() => {
		if (!holdingsBarChart) return;
		const handleClick = (params: any) => {
			const data = params?.data;
			if (!data?.name) return;
			selectedHolding = data.name;
			selectedHoldingCusip = data.cusip ?? null;
			selectedSector = data.sector ?? selectedSector;
		};
		holdingsBarChart.off("click");
		holdingsBarChart.on("click", handleClick);
		return () => {
			holdingsBarChart?.off("click", handleClick);
		};
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div class="sfm-overlay" onclick={onClose} role="dialog" aria-modal="true" aria-label={fundLabel} tabindex="-1">
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="sfm-modal" onclick={(event) => event.stopPropagation()} role="document">
		<div class="sfm-hero">
			<div>
				<h1 class="sfm-name">{detail?.name ?? fundLabel}</h1>
				<div class="sfm-meta">
					{#if loadingDetail}<span>Loading...</span>{/if}
					{#if detail?.manager_name}<span>{detail.manager_name}</span>{/if}
					{#if detail?.strategy_label}<span class="sfm-accent">{detail.strategy_label}</span>{/if}
					{#if detail?.fund_type}<span>{detail.fund_type.replace("_", " ").toUpperCase()}</span>{/if}
					{#if ticker}<span class="sfm-accent">{ticker}</span>{/if}
				</div>
			</div>
			{#if detail?.aum != null}
				<div class="sfm-aum">
					<span class="sfm-aum-val">{formatNumber(detail.aum / 1_000_000, 0)}M</span>
					<span class="sfm-aum-label">AUM</span>
				</div>
			{/if}
			<div class="sfm-hero-actions">
				<button type="button" class="sfm-link-btn" onclick={() => openResearch("fund")}>
					[ OPEN RESEARCH ]
				</button>
				<button type="button" class="sfm-close" onclick={onClose} aria-label="Close">
					[ ESC - CLOSE ]
				</button>
			</div>
		</div>

		<div class="sfm-kpi-grid">
			{#each [
				{ label: "1Y RETURN", value: percentText(detail?.avg_annual_return_1y, 2), tone: (detail?.avg_annual_return_1y ?? 0) >= 0 ? "up" : "down" },
				{ label: "10Y RETURN", value: percentText(detail?.avg_annual_return_10y, 2), tone: (detail?.avg_annual_return_10y ?? 0) >= 0 ? "up" : "down" },
				{ label: "SHARPE", value: detail?.sharpe_ratio != null ? formatNumber(detail.sharpe_ratio, 2) : "\u2014", tone: "" },
				{ label: "MAX DD", value: percentText(detail?.max_drawdown, 1), tone: "down" },
				{ label: "EXPENSE", value: detail?.expense_ratio_pct != null ? formatPercent(detail.expense_ratio_pct / 100, 2) : "\u2014", tone: "" },
				{ label: "SCORE", value: detail?.manager_score != null ? formatNumber(detail.manager_score, 0) : "\u2014", tone: "" },
			] as kpi (kpi.label)}
				<div class="sfm-kpi">
					<span class="sfm-kpi-label">{kpi.label}</span>
					<span class="sfm-kpi-value {kpi.tone}">{kpi.value}</span>
				</div>
			{/each}
		</div>

		<div class="sfm-body">
			<div class="sfm-tabs" role="tablist" aria-label="Fund focus views">
				<button type="button" class="sfm-tab" class:sfm-tab--active={focusTab === "performance"} role="tab" aria-selected={focusTab === "performance"} onclick={() => (focusTab = "performance")}>PERFORMANCE</button>
				<button type="button" class="sfm-tab" class:sfm-tab--active={focusTab === "profile"} role="tab" aria-selected={focusTab === "profile"} onclick={() => (focusTab = "profile")}>COMPOSITE PROFILE</button>
				<button type="button" class="sfm-tab" class:sfm-tab--active={focusTab === "analysis"} role="tab" aria-selected={focusTab === "analysis"} onclick={() => (focusTab = "analysis")}>DD</button>
				<button type="button" class="sfm-tab" class:sfm-tab--active={focusTab === "holdings"} role="tab" aria-selected={focusTab === "holdings"} onclick={() => (focusTab = "holdings")}>HOLDINGS</button>
				<button type="button" class="sfm-tab" class:sfm-tab--active={focusTab === "sectors"} role="tab" aria-selected={focusTab === "sectors"} onclick={() => (focusTab = "sectors")}>SECTORS</button>
			</div>

			<div class="sfm-stage">
				{#if focusTab === "performance"}
					<div class="sfm-panel sfm-panel--performance">
						<div class="sfm-subhead">
							<span>PERFORMANCE</span>
							<span>5Y NAV TRAIL</span>
						</div>
						<div class="sfm-perf-chart">
							{#if loadingNav}
								<div class="sfm-chart-empty">Loading...</div>
							{:else if perfChart.line}
								<svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none" width="100%" height="100%">
									<defs>
										<linearGradient id="sfm-g-{fundId}" x1="0" y1="0" x2="0" y2="1">
											<stop offset="0%" stop-color={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stop-opacity="0.35" />
											<stop offset="100%" stop-color={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stop-opacity="0" />
										</linearGradient>
									</defs>
									<path d={perfChart.area} fill="url(#sfm-g-{fundId})" />
									<path d={perfChart.line} fill="none" stroke={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stroke-width="1.5" />
								</svg>
							{:else}
								<div class="sfm-chart-empty">No NAV data</div>
							{/if}
						</div>

						<div class="sfm-performance-footer">
							<div class="sfm-period-grid">
								{#each periodStats as stat (stat.label)}
									<div class="sfm-period-row">
										<span class="sfm-period-lbl">{stat.label}</span>
										<span
											class="sfm-period-val"
											class:up={(stat.returnPct ?? 0) >= 0}
											class:down={(stat.returnPct ?? 0) < 0}
										>
											{stat.returnPct != null ? formatPercent(stat.returnPct, 2, "en-US", true) : "\u2014"}
										</span>
									</div>
								{/each}
							</div>

							{#if w52}
								<div class="sfm-52w">
									<span class="sfm-52w-lbl">52W</span>
									<span class="sfm-52w-val down">{formatCurrency(w52.low)}</span>
									<span class="sfm-52w-sep">-</span>
									<span class="sfm-52w-val up">{formatCurrency(w52.high)}</span>
								</div>
							{/if}
						</div>
					</div>
				{:else if focusTab === "profile"}
					<div class="sfm-panel sfm-panel--profile">
						<div class="sfm-subhead">
							<span>COMPOSITE PROFILE</span>
							<span>6 SIGNALS</span>
						</div>
						<div class="sfm-profile-stage">
							<div class="sfm-radar-wrap">
						<svg viewBox="0 0 {RADAR_W} {RADAR_H}" width={RADAR_W} height={RADAR_H}>
							{#each [0.25, 0.5, 0.75, 1.0] as pct}
								{@const pts = Array.from({ length: N }, (_, index) => {
									const p = radarPt(index, pct * R);
									return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
								})}
								<polygon points={pts.join(" ")} fill="none" stroke="var(--ii-border-subtle,#1A2458)" stroke-width="1" />
							{/each}
							{#each Array.from({ length: N }, (_, index) => index) as index (index)}
								{@const endpoint = radarPt(index, R)}
								<line x1={CX} y1={CY} x2={endpoint.x} y2={endpoint.y} stroke="var(--ii-border,#1A2458)" stroke-width="1" />
							{/each}
							<path d={radarPath} fill="var(--ii-brand-primary,#FF965A)" fill-opacity="0.18" stroke="var(--ii-brand-primary,#FF965A)" stroke-width="1.5" />
							{#each AXES as label, index (label)}
								{@const labelPoint = radarPt(index, R + 14)}
								<text x={labelPoint.x} y={labelPoint.y} text-anchor="middle" dominant-baseline="middle" font-family="var(--ii-font-mono)" font-size="7" fill="var(--ii-text-muted,#6D7DA6)">
									{label}
								</text>
							{/each}
						</svg>
							</div>

							<div class="sfm-axis-bars">
						{#each AXES as label, index (label)}
							{@const score = axisScores[index] ?? 0}
							<div class="sfm-axis-row">
								<span class="sfm-axis-lbl">{label}</span>
								<span class="sfm-axis-bar-wrap">
									<span class="sfm-axis-bar" style:width="{score}%"></span>
								</span>
								<span class="sfm-axis-val">{formatNumber(score, 0)}</span>
							</div>
						{/each}
							</div>
						</div>
					</div>
				{:else if focusTab === "analysis"}
					<div class="sfm-panel sfm-panel--analysis">
						<div class="sfm-analysis-grid">
							<div class="sfm-analysis-card">
								<div class="sfm-subhead">
									<span>PEER CONTEXT</span>
									{#if peerMetrics?.peer_count}
										<span>n={peerMetrics.peer_count}</span>
									{/if}
								</div>
					{#if peerMetrics && peerMetrics.peer_count > 0}
						<div class="sfm-peer-section">
							<h4 class="sfm-peer-hd">
								PEER GROUP
								{#if peerMetrics.strategy_label}
									<span class="sfm-peer-label">{peerMetrics.strategy_label}</span>
								{/if}
								<span class="sfm-peer-count">n={peerMetrics.peer_count}</span>
							</h4>

							<div class="sfm-peer-metric">
								<span class="sfm-peer-metric-name">SHARPE</span>
								<div class="sfm-peer-bar-wrap">
									<div class="sfm-peer-range" style:left="0%" style:width="100%"></div>
									{#if peerMetrics.subject_sharpe !== null}
										<div
											class="sfm-peer-subject"
											style:left={peerSubjectLeft(peerMetrics.subject_sharpe, peerMetrics.peer_sharpe_p25, peerMetrics.peer_sharpe_p75, 0, 1)}
										></div>
									{/if}
								</div>
								<div class="sfm-peer-vals">
									<span>p25: {peerMetrics.peer_sharpe_p25 != null ? formatNumber(peerMetrics.peer_sharpe_p25, 2) : "\u2014"}</span>
									<span>med: {peerMetrics.peer_sharpe_p50 != null ? formatNumber(peerMetrics.peer_sharpe_p50, 2) : "\u2014"}</span>
									<span class:sfm-peer-val-up={(peerMetrics.subject_sharpe ?? 0) >= (peerMetrics.peer_sharpe_p50 ?? 0)}>
										you: {peerMetrics.subject_sharpe != null ? formatNumber(peerMetrics.subject_sharpe, 2) : "\u2014"}
									</span>
								</div>
							</div>

							<div class="sfm-peer-metric">
								<span class="sfm-peer-metric-name">MAX DD</span>
								<div class="sfm-peer-bar-wrap">
									<div class="sfm-peer-range" style:left="0%" style:width="100%"></div>
									{#if peerMetrics.subject_drawdown !== null}
										<div
											class="sfm-peer-subject sfm-peer-subject--down"
											style:left={peerSubjectLeft(peerMetrics.subject_drawdown, peerMetrics.peer_drawdown_p25, peerMetrics.peer_drawdown_p75, -0.3, 0)}
										></div>
									{/if}
								</div>
								<div class="sfm-peer-vals">
									<span>p25: {percentText(peerMetrics.peer_drawdown_p25, 1)}</span>
									<span>med: {percentText(peerMetrics.peer_drawdown_p50, 1)}</span>
									<span class:sfm-peer-val-up={(peerMetrics.subject_drawdown ?? -1) >= (peerMetrics.peer_drawdown_p50 ?? -1)}>
										you: {percentText(peerMetrics.subject_drawdown, 1)}
									</span>
								</div>
							</div>
						</div>
					{:else if loadingPeer}
						<div class="sfm-analysis-empty">Loading peer data...</div>
					{:else}
						<div class="sfm-analysis-empty">No peer group data available.</div>
					{/if}
							</div>

							<div class="sfm-analysis-card">
								<div class="sfm-subhead">
									<span>DD REPORTS</span>
									{#if ddReports.length > 0}
										<span>{ddReports.length} REPORTS</span>
									{/if}
								</div>
					<div class="sfm-dd-section">
						<h4 class="sfm-peer-hd">DD REPORTS</h4>
						{#if loadingDD}
							<div class="sfm-analysis-empty">Loading...</div>
						{:else if ddReports.length === 0}
							<div class="sfm-analysis-empty">No DD reports generated yet.</div>
						{:else}
							{#each ddReports as report (report.id)}
								<div class="sfm-dd-row">
									<span class="sfm-dd-status sfm-dd-status--{report.status.toLowerCase()}">{report.status}</span>
									<span class="sfm-dd-ver">v{report.version}</span>
									<span class="sfm-dd-score">{report.confidence_score != null ? formatNumber(Number(report.confidence_score), 0) : "\u2014"}</span>
									<span class="sfm-dd-anchor">{report.decision_anchor ?? ""}</span>
								</div>
							{/each}
						{/if}
					</div>
							</div>
						</div>
					</div>
				{:else if focusTab === "holdings"}
					<div class="sfm-panel sfm-panel--holdings">
						<div class="sfm-subhead">
							<div class="sfm-subhead-main">
								<span>{selectedSector ? `${selectedSector} / HOLDINGS` : "TOP HOLDINGS"}</span>
								{#if selectedHolding}
									<span class="sfm-accent">FOCUS {selectedHolding}</span>
								{/if}
							</div>
							<div class="sfm-subhead-actions">
								{#if selectedSector}
									<button type="button" class="sfm-inline-btn" onclick={clearHoldingsFilter}>
										[ CLEAR FILTER ]
									</button>
								{/if}
								{#if holdingsData?.as_of}
									<span>AS OF {holdingsData.as_of}</span>
								{/if}
							</div>
						</div>

						{#if loadingHoldings}
							<div class="sfm-analysis-empty">Loading holdings...</div>
						{:else if displayedHoldings.length === 0}
							<div class="sfm-analysis-empty">
								{selectedSector
									? `No disclosed holdings mapped to ${selectedSector}.`
									: holdingsData?.disclosure?.message ?? "No holdings disclosure available."}
							</div>
						{:else}
							<div class="sfm-holdings-layout">
								<div class="sfm-holdings-hero">
									<div class="sfm-holdings-chart">
										<ChartContainer
											bind:chart={holdingsBarChart}
											height={420}
											option={holdingsBarOption}
											loading={loadingHoldings}
											empty={topHoldings.length === 0}
											emptyMessage={holdingsData?.disclosure?.message ?? "No holdings disclosure available."}
											ariaLabel="Top holdings concentration chart"
										/>
									</div>

									<div class="sfm-holdings-summary">
										<div class="sfm-holdings-stat">
											<span class="sfm-holdings-stat-label">TOP 3</span>
											<span class="sfm-holdings-stat-value">{holdingWeightText(holdingsStats.top3)}</span>
										</div>
										<div class="sfm-holdings-stat">
											<span class="sfm-holdings-stat-label">TOP 5</span>
											<span class="sfm-holdings-stat-value">{holdingWeightText(holdingsStats.top5)}</span>
										</div>
										<div class="sfm-holdings-stat">
											<span class="sfm-holdings-stat-label">TOP 10</span>
											<span class="sfm-holdings-stat-value">{holdingWeightText(holdingsStats.top10)}</span>
										</div>
										<div class="sfm-holdings-stat">
											<span class="sfm-holdings-stat-label">POSITIONS</span>
											<span class="sfm-holdings-stat-value">{formatNumber(holdingsStats.positions, 0)}</span>
										</div>
									</div>
								</div>

								<div class="sfm-holdings-note">
									{#if selectedSector}
										Filtered from the sector map. Table below isolates the disclosed names inside {selectedSector}.
									{:else}
										Top concentration by position. Table below remains available for precise sector and market value readout.
									{/if}
								</div>

								{#if selectedHoldingData}
									<div class="sfm-holding-focus">
										<div class="sfm-holding-focus-hero">
											<div>
												<div class="sfm-subhead sfm-subhead--tight">
													<span>HOLDING LENS</span>
													<span>{selectedHoldingData.cusip ?? "CUSIP N/A"}</span>
												</div>
												<div class="sfm-holding-focus-name">{selectedHoldingData.issuer_name}</div>
												<div class="sfm-meta">
													<span>{selectedHoldingData.sector ?? "Unknown Sector"}</span>
													{#if reverseLookup?.company_name}
														<span>{reverseLookup.company_name}</span>
													{/if}
													{#if reverseLookup?.holders?.[0]?.report_date}
														<span>Filed {reverseLookup.holders[0].report_date}</span>
													{/if}
												</div>
											</div>
											<div class="sfm-holding-focus-actions">
												<button type="button" class="sfm-inline-btn" onclick={() => openResearch("holdings")}>
													[ OPEN RESEARCH ]
												</button>
												<button
													type="button"
													class="sfm-inline-btn"
													onclick={() => {
														selectedHoldingCusip = null;
														selectedHolding = null;
													}}
												>
													[ CLEAR LENS ]
												</button>
											</div>
										</div>

										<div class="sfm-holding-focus-grid">
											<div class="sfm-sector-focus-stat">
												<span class="sfm-holdings-stat-label">WEIGHT</span>
												<span class="sfm-holdings-stat-value">{holdingWeightText(selectedHoldingData.weight)}</span>
											</div>
											<div class="sfm-sector-focus-stat">
												<span class="sfm-holdings-stat-label">MARKET VALUE</span>
												<span class="sfm-holdings-stat-value">{moneyText(selectedHoldingData.market_value)}</span>
											</div>
											<div class="sfm-sector-focus-stat">
												<span class="sfm-holdings-stat-label">INSTITUTIONAL HOLDERS</span>
												<span class="sfm-holdings-stat-value">
													{loadingReverseLookup ? "…" : formatNumber(reverseLookup?.total_holders ?? 0, 0)}
												</span>
											</div>
											<div class="sfm-sector-focus-stat">
												<span class="sfm-holdings-stat-label">TOP HOLDER</span>
												<span class="sfm-holding-focus-inline">
													{#if loadingReverseLookup}
														Loading...
													{:else if reverseLookup?.holders?.[0]}
														{reverseLookup.holders[0].firm_name}
													{:else}
														—
													{/if}
												</span>
											</div>
											<div class="sfm-sector-focus-list">
												<span class="sfm-holdings-stat-label">TOP HOLDERS</span>
												{#if loadingReverseLookup}
													<div class="sfm-analysis-empty">Loading reverse lookup...</div>
												{:else if reverseLookup?.holders?.length}
													{#each reverseLookup.holders.slice(0, 5) as holder (`${selectedHoldingData.issuer_name}-${holder.cik}`)}
														<div class="sfm-sector-focus-row">
															<span class="sfm-holding-name">{holder.firm_name}</span>
															<span class="sfm-num">
																{holder.pct_of_total != null ? formatPercent(holder.pct_of_total, 1) : moneyText(holder.market_value)}
															</span>
														</div>
													{/each}
												{:else}
													<div class="sfm-analysis-empty">No institutional holder map available for this CUSIP.</div>
												{/if}
											</div>
										</div>

										<div class="sfm-holding-deep-dive">
											<div class="sfm-holding-deep-panel">
												<div class="sfm-subhead sfm-subhead--tight">
													<span>OWNERSHIP TRAIL</span>
													<span>{selectedHoldingData.cusip ?? "CUSIP N/A"}</span>
												</div>
												{#if loadingHoldingHistory}
													<div class="sfm-analysis-empty">Loading ownership history...</div>
												{:else if holdingHistory?.quarters?.length}
													<div class="sfm-holding-history-chart">
														<ChartContainer
															option={holdingsHistoryOption}
															height={240}
														/>
													</div>
												{:else}
													<div class="sfm-analysis-empty">No ownership trail available for this security.</div>
												{/if}
											</div>

											<div class="sfm-holding-deep-panel">
												<div class="sfm-subhead sfm-subhead--tight">
													<span>HOLDER MAP</span>
													{#if reverseLookup?.total_holders != null}
														<span>{formatNumber(reverseLookup.total_holders, 0)} HOLDERS</span>
													{/if}
												</div>
												{#if loadingReverseLookup}
													<div class="sfm-analysis-empty">Loading holder map...</div>
												{:else if reverseLookup?.holders?.length}
													<div class="sfm-holder-list">
														{#each reverseLookup.holders as holder (`${selectedHoldingData.issuer_name}-${holder.cik}`)}
															<button
																type="button"
																class="sfm-holder-row"
																class:sfm-holder-row--active={activeHolderCik === holder.cik}
																onclick={() => (activeHolderCik = holder.cik)}
															>
																<span class="sfm-holding-name">{holder.firm_name}</span>
																<span class="sfm-holder-meta">
																	{holder.pct_of_total != null ? formatPercent(holder.pct_of_total, 1) : "—"}
																</span>
															</button>
														{/each}
													</div>
												{:else}
													<div class="sfm-analysis-empty">No institutional holders found for this security.</div>
												{/if}
											</div>

											<div class="sfm-holding-deep-panel">
												<div class="sfm-subhead sfm-subhead--tight">
													<span>MANAGER SNAPSHOT</span>
													{#if activeHolder}
														<span>{activeHolder.cik}</span>
													{/if}
												</div>
												{#if loadingActiveHolderManager}
													<div class="sfm-analysis-empty">Loading manager detail...</div>
												{:else if activeHolderManager}
													<div class="sfm-manager-lens">
														<div class="sfm-manager-lens-name">{activeHolderManager.firm_name}</div>
														<div class="sfm-meta">
															{#if activeHolderManager.registration_status}
																<span>{activeHolderManager.registration_status}</span>
															{/if}
															{#if activeHolderManager.country}
																<span>{activeHolderManager.country}</span>
															{/if}
															{#if activeHolderManager.latest_quarter}
																<span>Quarter {activeHolderManager.latest_quarter}</span>
															{/if}
														</div>

														<div class="sfm-manager-lens-grid">
															<div class="sfm-manager-lens-stat">
																<span class="sfm-holdings-stat-label">AUM</span>
																<span class="sfm-holding-focus-inline">{moneyText(activeHolderManager.aum_total)}</span>
															</div>
															<div class="sfm-manager-lens-stat">
																<span class="sfm-holdings-stat-label">HOLDINGS</span>
																<span class="sfm-holding-focus-inline">{formatNumber(activeHolderManager.holdings_count, 0)}</span>
															</div>
															<div class="sfm-manager-lens-stat">
																<span class="sfm-holdings-stat-label">PORTFOLIO VALUE</span>
																<span class="sfm-holding-focus-inline">{moneyText(activeHolderManager.total_portfolio_value)}</span>
															</div>
															<div class="sfm-manager-lens-stat">
																<span class="sfm-holdings-stat-label">PRIVATE FUNDS</span>
																<span class="sfm-holding-focus-inline">
																	{formatNumber(activeHolderManager.private_fund_count ?? 0, 0)}
																</span>
															</div>
														</div>
													</div>
												{:else}
													<div class="sfm-analysis-empty">No manager profile available for this holder.</div>
												{/if}
											</div>
										</div>
									</div>
								{/if}

								<div class="sfm-holdings-mix">
									<div class="sfm-subhead sfm-subhead--tight">
										<span>DISCLOSED TOP POSITIONS / SECTOR MIX</span>
										<span>{holdingWeightText(disclosedTopWeight)} OF DISCLOSED BOOK</span>
									</div>
									<div class="sfm-holdings-strip">
										{#each holdingsSectorMix.slice(0, 8) as sector (sector.name)}
											<button
												type="button"
												class="sfm-holdings-strip-segment"
												class:sfm-holdings-strip-segment--active={selectedSector === sector.name}
												style:width={sectorMixWidth(sector.weight)}
												style:background={sector.color}
												title={`${sector.name} · ${holdingWeightText(sector.weight)} · ${sector.count} holdings`}
												onclick={() => focusSector(sector.name, "sectors")}
											></button>
										{/each}
									</div>
									<div class="sfm-holdings-mix-grid">
										{#each holdingsSectorMix.slice(0, 6) as sector (sector.name)}
											<button
												type="button"
												class="sfm-holdings-mix-row"
												class:sfm-holdings-mix-row--active={selectedSector === sector.name}
												onclick={() => focusSector(sector.name, "sectors")}
											>
												<div class="sfm-holdings-mix-label">
													<span class="sfm-holdings-mix-dot" style:background={sector.color}></span>
													<span class="sfm-sector-name">{sector.name}</span>
												</div>
												<span class="sfm-holdings-mix-count">{sector.count} holdings</span>
												<span class="sfm-num">{holdingWeightText(sector.weight)}</span>
											</button>
										{/each}
									</div>
								</div>

								<div class="sfm-holdings-table sfm-holdings-table--wide">
									<div class="sfm-holdings-row sfm-holdings-row--head">
										<span>NAME</span>
										<span>SECTOR</span>
										<span>MAP</span>
										<span>WGT</span>
										<span>VALUE</span>
									</div>
									{#each displayedHoldings.slice(0, 12) as holding, index (`${holding.issuer_name}-${index}`)}
										<button
											type="button"
											class="sfm-holdings-row"
											class:sfm-holdings-row--active={
												(selectedHoldingCusip && holding.cusip === selectedHoldingCusip) ||
												selectedHolding === holding.issuer_name
											}
											onclick={() => focusHolding(holding)}
										>
											<span class="sfm-holding-name">{holding.issuer_name}</span>
											<span class:sfm-sector-name={Boolean(selectedSector)}>{holding.sector ?? "\u2014"}</span>
											<span class="sfm-holdings-map-cell">
												<span class="sfm-holdings-map-rail">
													<span
														class="sfm-holdings-map-fill"
														class:sfm-holdings-map-fill--selected={
															(selectedHoldingCusip && holding.cusip === selectedHoldingCusip) ||
															selectedHolding === holding.issuer_name
														}
														style:width={relativeWeightWidth(holding.weight)}
													></span>
												</span>
											</span>
											<span class="sfm-num">{holdingWeightText(holding.weight)}</span>
											<span class="sfm-num">{moneyText(holding.market_value)}</span>
										</button>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				{:else}
					<div class="sfm-panel sfm-panel--sectors">
						<div class="sfm-subhead">
							<div class="sfm-subhead-main">
								<span>{activeSectorSummary ? `${activeSectorSummary.name} / SECTOR LENS` : "SECTOR / HOLDINGS MAP"}</span>
							</div>
							<div class="sfm-subhead-actions">
								{#if activeSectorSummary}
									<button type="button" class="sfm-inline-btn" onclick={() => (focusTab = "holdings")}>
										[ OPEN IN HOLDINGS ]
									</button>
									<button type="button" class="sfm-inline-btn" onclick={clearHoldingsFilter}>
										[ CLEAR FOCUS ]
									</button>
								{/if}
								{#if sectorBreakdown.length > 0}
									<span>{sectorBreakdown.length} GROUPS</span>
								{/if}
							</div>
						</div>

						{#if loadingHoldings}
							<div class="sfm-analysis-empty">Loading sectors...</div>
						{:else if sectorBreakdown.length === 0}
							<div class="sfm-analysis-empty">
								{holdingsData?.disclosure?.message ?? "No sector breakdown available."}
							</div>
						{:else}
							<div class="sfm-sector-treemap">
								<ChartContainer
									bind:chart={sectorTreemapChart}
									height={620}
									option={sectorTreemapOption}
									loading={loadingHoldings}
									empty={treemapData.length === 0}
									emptyMessage={holdingsData?.disclosure?.message ?? "No sector breakdown available."}
									ariaLabel="Sector and holdings treemap"
								/>
							</div>
							<div class="sfm-sector-note">Click a sector to zoom into its holdings. Breadcrumb returns to the portfolio view.</div>
							{#if activeSectorSummary}
								<div class="sfm-sector-focus">
									<div class="sfm-sector-focus-stat">
										<span class="sfm-holdings-stat-label">SECTOR WT</span>
										<span class="sfm-holdings-stat-value">{holdingWeightText(activeSectorSummary.totalWeight)}</span>
									</div>
									<div class="sfm-sector-focus-stat">
										<span class="sfm-holdings-stat-label">DISCLOSED WT</span>
										<span class="sfm-holdings-stat-value">{holdingWeightText(activeSectorSummary.disclosedWeight)}</span>
									</div>
									<div class="sfm-sector-focus-stat">
										<span class="sfm-holdings-stat-label">POSITIONS</span>
										<span class="sfm-holdings-stat-value">{formatNumber(activeSectorSummary.holdingsCount, 0)}</span>
									</div>
									<div class="sfm-sector-focus-list">
										<span class="sfm-holdings-stat-label">TOP NAMES</span>
										{#each activeSectorSummary.topNames as holding (`${activeSectorSummary.name}-${holding.issuer_name}`)}
											<div class="sfm-sector-focus-row">
												<span class="sfm-holding-name">{holding.issuer_name}</span>
												<span class="sfm-num">{holdingWeightText(holding.weight)}</span>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.sfm-overlay {
		position: fixed;
		inset: 0;
		z-index: 9999;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(5, 8, 26, 0.72);
	}

	.sfm-modal {
		position: relative;
		display: flex;
		flex-direction: column;
		width: 1360px;
		max-width: 96vw;
		height: 92vh;
		max-height: 92vh;
		overflow: hidden;
		border: 1px solid var(--ii-border, #1A2458);
		background: var(--ii-surface, #0B1230);
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
	}

	.sfm-hero {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		align-items: start;
		flex-shrink: 0;
		gap: 18px;
		padding: 18px 20px;
		border-bottom: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-name {
		margin: 0 0 4px;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-family: var(--ii-font-sans, var(--terminal-font-sans, var(--terminal-font-mono)));
		font-size: 22px;
		font-weight: 300;
	}

	.sfm-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		margin-top: 6px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-accent {
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
		font-weight: 600;
	}

	.sfm-aum {
		min-width: 120px;
		text-align: right;
	}

	.sfm-hero-actions {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}

	.sfm-link-btn,
	.sfm-close {
		align-self: start;
		min-width: 112px;
		padding: 5px 10px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: transparent;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		letter-spacing: 0.08em;
		cursor: pointer;
	}

	.sfm-link-btn {
		min-width: 132px;
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
		border-color: color-mix(in srgb, var(--ii-brand-primary, var(--terminal-accent-amber)) 55%, transparent);
	}

	.sfm-aum-val {
		display: block;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 20px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-aum-label,
	.sfm-kpi-label,
	.sfm-sh,
	.sfm-period-lbl,
	.sfm-52w-lbl,
	.sfm-axis-lbl {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-kpi-grid {
		display: grid;
		grid-template-columns: repeat(6, minmax(0, 1fr));
		flex-shrink: 0;
		gap: 1px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-kpi {
		padding: 10px 12px;
		background: var(--ii-surface, var(--terminal-bg-panel));
	}

	.sfm-kpi-label {
		display: block;
	}

	.sfm-kpi-value {
		display: block;
		margin-top: 4px;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 20px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-kpi-value.up,
	.sfm-period-val.up,
	.sfm-52w-val.up {
		color: var(--ii-success, var(--terminal-status-success));
	}

	.sfm-kpi-value.down,
	.sfm-period-val.down,
	.sfm-52w-val.down {
		color: var(--ii-danger, var(--terminal-status-error));
	}

	.sfm-body {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface, var(--terminal-bg-panel));
	}

	.sfm-tabs {
		display: grid;
		grid-template-columns: 1fr 1fr 0.75fr 0.8fr 0.8fr;
		flex-shrink: 0;
		gap: 1px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-tab {
		min-width: 0;
		height: 42px;
		border: none;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.sfm-tab--active {
		background: var(--ii-surface, var(--terminal-bg-panel));
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
		box-shadow: inset 0 -2px 0 var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-stage {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding: 20px;
		border-top: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-panel {
		display: flex;
		flex-direction: column;
		min-height: 100%;
	}

	.sfm-panel--performance {
		min-height: 0;
	}

	.sfm-panel--profile,
	.sfm-panel--holdings,
	.sfm-panel--sectors {
		min-height: 0;
	}

	.sfm-profile-stage {
		display: grid;
		grid-template-columns: minmax(320px, 0.95fr) minmax(0, 1.05fr);
		gap: 22px;
		align-items: start;
	}

	.sfm-analysis-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.1fr) minmax(380px, 0.9fr);
		gap: 22px;
		min-height: 0;
	}

	.sfm-analysis-card {
		min-height: 0;
		padding: 14px 16px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: color-mix(in srgb, var(--ii-surface-alt, var(--terminal-bg-panel-sunken)) 55%, transparent);
	}

	.sfm-sh {
		margin: 0 0 10px;
		font-size: 10px;
		font-weight: 700;
	}

	.sfm-perf-chart {
		height: 520px;
		margin-bottom: 18px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 10px;
	}

	.sfm-period-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 6px 18px;
		margin-bottom: 12px;
	}

	.sfm-period-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 7px 0;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
	}

	.sfm-period-val {
		font-size: 16px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-performance-footer {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.sfm-52w {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 8px;
		font-size: 10px;
	}

	.sfm-52w-val {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-52w-sep {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.sfm-radar-wrap {
		display: flex;
		justify-content: center;
		padding: 8px 0 0;
	}

	.sfm-axis-bars {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-top: 8px;
	}

	.sfm-axis-row {
		display: grid;
		grid-template-columns: 90px 1fr 32px;
		align-items: center;
		gap: 10px;
	}

	.sfm-axis-lbl {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-axis-bar-wrap {
		position: relative;
		display: block;
		height: 8px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		border-radius: 1px;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-axis-bar {
		position: absolute;
		inset: 0 auto 0 0;
		background: var(--ii-brand-primary, var(--terminal-accent-amber));
		transition: width 200ms ease;
	}

	.sfm-axis-val {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 12px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.sfm-link-btn:hover,
	.sfm-close:hover {
		border-color: var(--ii-brand-primary, var(--terminal-accent-amber));
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-peer-section {
		margin-bottom: 0;
	}

	.sfm-peer-hd {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0 0 8px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-peer-label {
		overflow: hidden;
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-peer-count {
		margin-left: auto;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.sfm-peer-metric {
		margin-bottom: 10px;
	}

	.sfm-peer-metric-name {
		display: block;
		margin-bottom: 4px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.sfm-peer-bar-wrap {
		position: relative;
		height: 10px;
		margin-bottom: 4px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-peer-range {
		position: absolute;
		top: 0;
		bottom: 0;
		background: var(--ii-border-subtle, rgba(102, 137, 188, 0.26));
	}

	.sfm-peer-subject {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 2px;
		background: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-peer-subject--down {
		background: var(--ii-danger, var(--terminal-status-error));
	}

	.sfm-peer-vals {
		display: flex;
		gap: 10px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		font-variant-numeric: tabular-nums;
	}

	.sfm-peer-val-up {
		color: var(--ii-success, var(--terminal-status-success));
		font-weight: 700;
	}

	.sfm-dd-section {
		padding-top: 0;
		border-top: none;
	}

	.sfm-dd-row {
		display: grid;
		grid-template-columns: 88px 28px 36px minmax(0, 1fr);
		gap: 8px;
		align-items: center;
		padding: 3px 0;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
	}

	.sfm-dd-status {
		overflow: hidden;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-overflow: ellipsis;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.sfm-dd-status--approved {
		color: var(--ii-success, var(--terminal-status-success));
	}

	.sfm-dd-status--pending,
	.sfm-dd-status--pending_approval {
		color: var(--ii-warning, var(--terminal-status-warn));
	}

	.sfm-dd-status--rejected,
	.sfm-dd-status--failed {
		color: var(--ii-danger, var(--terminal-status-error));
	}

	.sfm-dd-status--generating {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.sfm-dd-ver {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
	}

	.sfm-dd-score {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-dd-anchor {
		overflow: hidden;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-analysis-empty {
		padding: 12px 0;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
	}

	.sfm-subhead {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 10px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-subhead-main,
	.sfm-subhead-actions {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}

	.sfm-subhead--tight {
		margin-bottom: 8px;
	}

	.sfm-inline-btn {
		height: 24px;
		padding: 0 10px;
		border: 1px solid var(--ii-border, var(--terminal-fg-muted));
		background: transparent;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-inline-btn:hover {
		border-color: var(--ii-brand-primary, var(--terminal-accent-amber));
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-sector-treemap {
		flex: 1;
		min-height: 0;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: color-mix(in srgb, var(--ii-surface-alt, var(--terminal-bg-panel-sunken)) 70%, transparent);
	}

	.sfm-sector-note {
		margin-top: 12px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.sfm-sector-focus {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 180px)) minmax(0, 1fr);
		gap: 1px;
		margin-top: 12px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-sector-focus-stat,
	.sfm-sector-focus-list {
		padding: 14px 16px;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-sector-focus-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		min-width: 0;
	}

	.sfm-sector-focus-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		align-items: center;
		min-height: 22px;
		padding-bottom: 6px;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
	}

	.sfm-holdings-layout {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-height: 0;
	}

	.sfm-holdings-hero {
		display: grid;
		grid-template-columns: minmax(0, 1.8fr) minmax(220px, 0.72fr);
		gap: 14px;
		min-height: 0;
	}

	.sfm-holdings-chart {
		min-height: 0;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: color-mix(in srgb, var(--ii-surface-alt, var(--terminal-bg-panel-sunken)) 70%, transparent);
	}

	.sfm-holdings-summary {
		display: grid;
		grid-template-columns: 1fr;
		gap: 1px;
		align-self: stretch;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-holdings-stat {
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 8px;
		padding: 16px 18px;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-holdings-stat-label {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-holdings-stat-value {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 26px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.sfm-holdings-note {
		margin-top: 12px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.sfm-holding-focus {
		display: flex;
		flex-direction: column;
		gap: 12px;
		margin-top: 12px;
		padding: 14px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: color-mix(in srgb, var(--ii-surface-alt, var(--terminal-bg-panel-sunken)) 72%, transparent);
	}

	.sfm-holding-focus-hero {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}

	.sfm-holding-focus-name {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 20px;
		font-weight: 700;
		line-height: 1.1;
	}

	.sfm-holding-focus-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
	}

	.sfm-holding-focus-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 180px)) minmax(0, 1.25fr);
		gap: 1px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-holding-focus-inline {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 13px;
		font-weight: 600;
		line-height: 1.35;
	}

	.sfm-holding-deep-dive {
		display: grid;
		grid-template-columns: minmax(0, 1.35fr) minmax(240px, 0.8fr) minmax(260px, 0.95fr);
		gap: 12px;
	}

	.sfm-holding-deep-panel {
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-height: 0;
		padding: 12px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: color-mix(in srgb, var(--ii-surface-alt, var(--terminal-bg-panel-sunken)) 68%, transparent);
	}

	.sfm-holding-history-chart {
		flex: 1;
		min-height: 0;
	}

	.sfm-holder-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-holder-row {
		appearance: none;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		align-items: center;
		padding: 10px 12px;
		border: none;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
		text-align: left;
		transition:
			background-color 120ms ease,
			color 120ms ease;
	}

	.sfm-holder-row:hover,
	.sfm-holder-row:focus-visible {
		background: rgba(102, 137, 188, 0.08);
		outline: none;
	}

	.sfm-holder-row--active {
		background: rgba(255, 154, 77, 0.08);
	}

	.sfm-holder-row--active .sfm-holding-name,
	.sfm-holder-row--active .sfm-holder-meta {
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-holder-meta {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 10px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.sfm-manager-lens {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.sfm-manager-lens-name {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 15px;
		font-weight: 700;
		line-height: 1.25;
	}

	.sfm-manager-lens-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-manager-lens-stat {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 12px;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-holdings-mix {
		margin-top: 12px;
		padding: 12px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: color-mix(in srgb, var(--ii-surface-alt, var(--terminal-bg-panel-sunken)) 62%, transparent);
	}

	.sfm-holdings-strip {
		display: flex;
		height: 14px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: rgba(102, 137, 188, 0.1);
	}

	.sfm-holdings-strip-segment {
		appearance: none;
		padding: 0;
		min-width: 0;
		border-right: 1px solid rgba(11, 18, 48, 0.9);
	}

	.sfm-holdings-strip-segment--active {
		box-shadow: inset 0 0 0 2px rgba(255, 243, 214, 0.85);
	}

	.sfm-holdings-mix-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px 14px;
		margin-top: 12px;
	}

	.sfm-holdings-mix-row {
		appearance: none;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		gap: 10px;
		align-items: center;
		min-height: 24px;
		padding-bottom: 6px;
		padding-inline: 0;
		border: none;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
		background: transparent;
		text-align: left;
	}

	.sfm-holdings-mix-row--active {
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-holdings-mix-label {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.sfm-holdings-mix-dot {
		width: 8px;
		height: 8px;
		flex-shrink: 0;
	}

	.sfm-holdings-mix-count {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.sfm-holdings-table {
		margin-top: 12px;
		border-top: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
	}

	.sfm-holdings-table--wide {
		flex: 1;
		min-height: 0;
	}

	.sfm-holdings-row {
		appearance: none;
		display: grid;
		grid-template-columns: minmax(0, 1.7fr) minmax(160px, 0.8fr) minmax(120px, 0.7fr) 100px 120px;
		gap: 12px;
		align-items: center;
		width: 100%;
		min-height: 34px;
		padding: 0;
		padding-inline: 0;
		border: none;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
		background: transparent;
		color: var(--ii-text-secondary, var(--terminal-fg-secondary));
		font-size: 11px;
		text-align: left;
		transition:
			background-color 120ms ease,
			color 120ms ease,
			border-color 120ms ease;
	}

	.sfm-holdings-row:not(.sfm-holdings-row--head):hover {
		background: rgba(102, 137, 188, 0.08);
	}

	.sfm-holdings-row:not(.sfm-holdings-row--head):focus-visible {
		outline: 1px solid var(--ii-brand-primary, var(--terminal-accent-amber));
		outline-offset: -1px;
		background: rgba(255, 154, 77, 0.08);
	}

	.sfm-holdings-row--head {
		min-height: 22px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 8px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-holdings-row--active {
		background: rgba(255, 154, 77, 0.08);
	}

	.sfm-holdings-row--active .sfm-holding-name,
	.sfm-holdings-row--active .sfm-num,
	.sfm-holdings-row--active .sfm-sector-name {
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-holding-name,
	.sfm-sector-name {
		overflow: hidden;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-num {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.sfm-holdings-map-cell {
		display: flex;
		align-items: center;
	}

	.sfm-holdings-map-rail {
		position: relative;
		display: block;
		width: 100%;
		height: 8px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: rgba(102, 137, 188, 0.08);
	}

	.sfm-holdings-map-fill {
		position: absolute;
		inset: 0 auto 0 0;
		background: linear-gradient(90deg, #ff9a4d 0%, #3dd39a 100%);
	}

	.sfm-holdings-map-fill--selected {
		background: linear-gradient(90deg, #ffb36c 0%, #ffd47c 100%);
	}

	@media (max-width: 1180px) {
		.sfm-tabs {
			grid-template-columns: repeat(5, minmax(0, 1fr));
		}

		.sfm-profile-stage,
		.sfm-analysis-grid,
		.sfm-holdings-hero {
			grid-template-columns: 1fr;
		}

		.sfm-holding-focus-hero {
			flex-direction: column;
		}

		.sfm-holding-deep-dive,
		.sfm-manager-lens-grid {
			grid-template-columns: 1fr;
		}

		.sfm-perf-chart {
			height: 420px;
		}

		.sfm-holdings-stat-value {
			font-size: 22px;
		}

		.sfm-holdings-mix-grid {
			grid-template-columns: 1fr;
		}

		.sfm-holdings-row {
			grid-template-columns: minmax(0, 1.5fr) minmax(120px, 0.8fr) minmax(90px, 0.7fr) 84px 108px;
			gap: 10px;
		}

		.sfm-subhead {
			flex-direction: column;
			align-items: flex-start;
		}

		.sfm-sector-focus {
			grid-template-columns: 1fr;
		}

		.sfm-holding-focus-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
