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

	interface Holding {
		issuer_name: string;
		cusip: string;
		sector: string;
		weight: number | null;
		market_value: number | null;
	}

	interface HoldingsPayload {
		top_holdings: Holding[];
	}

	interface Institution {
		institution_id: string;
		name: string;
		category: string;
		cik?: string | null;
		country?: string | null;
		total_overlap?: number;
		total_value?: number;
	}

	interface RevealPayload {
		institutions: Institution[];
		overlap_matrix: Record<string, Record<string, number>>;
	}

	interface GraphNode {
		id: string;
		name: string;
		category: "holding" | "holder";
		symbolSize: number;
		value?: number;
		source?: string;
	}

	interface GraphEdge {
		source: string;
		target: string;
	}

	interface ReverseLookupPayload {
		nodes: GraphNode[];
		edges: GraphEdge[];
		target_cusip: string;
	}

	interface ManagerDetail {
		crd_number: string;
		cik: string | null;
		firm_name: string;
		registration_status?: string | null;
		aum_total?: number | null;
		state?: string | null;
		country?: string | null;
		website?: string | null;
		latest_quarter?: string | null;
		holdings_count?: number | null;
		total_portfolio_value?: number | null;
		private_fund_count?: number | null;
		hedge_fund_count?: number | null;
		pe_fund_count?: number | null;
		vc_fund_count?: number | null;
		total_private_fund_assets?: number | null;
		linked_13f_ciks?: string[] | null;
	}

	interface FundDetail {
		cik: string;
		fund_name: string;
		fund_type: string;
		ticker?: string | null;
		total_assets?: number | null;
		currency?: string | null;
		domicile?: string | null;
		last_nport_date?: string | null;
	}

	interface OwnershipHistoryPoint {
		quarter: string;
		total_holders: number;
		total_market_value: number;
	}

	interface OwnershipHistory {
		cusip: string;
		quarters: OwnershipHistoryPoint[];
	}

	interface FundBreakdownItem {
		fund_type: string;
		fund_count: number;
		pct_of_total: number;
	}

	interface FundBreakdown {
		crd_number: string;
		total_funds: number;
		breakdown: FundBreakdownItem[];
	}

	interface ManagerCompareManager extends ManagerDetail {}

	interface PeerHoldingOverlap {
		cik_a: string;
		cik_b: string;
		overlap_pct: number;
	}

	interface ManagerComparePayload {
		managers: ManagerCompareManager[];
		sector_allocations: Record<string, Record<string, number>>;
		overlaps: PeerHoldingOverlap[];
		hhi_scores: Record<string, number>;
		fund_breakdowns: Record<string, FundBreakdown>;
	}

	type SourceMode = "all" | "13f" | "nport" | "curated";
	type LowerMode = "entity" | "compare" | "ownership";

	type DisplayNode = {
		id: string;
		displayId: string;
		name: string;
		source: "13f" | "nport" | "curated";
		value: number | null;
		category?: string | null;
		country?: string | null;
		managerCik?: string | null;
	};

	let { fundId, ticker, label = "—" }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	let holdings = $state<Holding[]>([]);
	let reveal = $state<RevealPayload | null>(null);
	let selectedCusip = $state<string | null>(null);
	let graph = $state<ReverseLookupPayload | null>(null);
	let sourceMode = $state<SourceMode>("all");
	let selectedHolderId = $state<string | null>(null);
	let loading = $state(false);
	let graphLoading = $state(false);
	let inspectorLoading = $state(false);
	let error = $state<string | null>(null);
	let managerDetail = $state<ManagerDetail | null>(null);
	let fundDetail = $state<FundDetail | null>(null);
	let ownershipHistory = $state<OwnershipHistory | null>(null);
	let fundBreakdown = $state<FundBreakdown | null>(null);
	let compareLoading = $state(false);
	let managerCompare = $state<ManagerComparePayload | null>(null);
	let compareSelection = $state<string[]>([]);
	let anchorManagerCik = $state<string | null>(null);
	let lowerMode = $state<LowerMode>("entity");
	let graphChart = $state<any>();

	function percent(value: number | null | undefined, digits = 1): string {
		if (value == null) return "—";
		return formatPercent(Math.abs(value) > 1 ? value / 100 : value, digits);
	}

	function compactMoney(value: number | null | undefined): string {
		if (value == null) return "—";
		return formatCompact(value);
	}

	function sourceLabel(value: SourceMode | DisplayNode["source"]): string {
		if (value === "13f") return "Manager";
		if (value === "nport") return "Fund";
		if (value === "curated") return "Institution";
		return "ALL";
	}

	function sourceFilterLabel(value: SourceMode): string {
		if (value === "13f") return "MANAGERS";
		if (value === "nport") return "FUNDS";
		if (value === "curated") return "INSTITUTIONS";
		return "ALL";
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

	function shortenEntityLabel(value: string | null | undefined, max = 24): string {
		const cleaned = cleanLabel(value);
		if (cleaned === "—") return cleaned;
		const compacted = cleaned
			.replace(/\b(Incorporated|Corporation|Company|Holdings?|Limited|Trust|Group|Partners?)\b/gi, "")
			.replace(/\b(Inc|Corp|Co|Ltd|LLC|PLC|LP|NV|AG|SE|SA)\b\.?/gi, "")
			.replace(/\s{2,}/g, " ")
			.trim();
		const normalized = compacted || cleaned;
		if (normalized.length <= max) return normalized;
		return `${normalized.slice(0, Math.max(8, max - 1)).trimEnd()}…`;
	}

	function lensLabel(mode: LowerMode): string {
		if (mode === "entity") return "Anchor View";
		if (mode === "compare") return "Manager Overlap";
		return "Market Ownership";
	}

	function lensDescription(mode: LowerMode): string {
		if (mode === "entity") {
			return selectedHolder
				? `${cleanLabel(selectedHolder.name)} · ${sourceLabel(selectedHolder.source)} profile`
				: "Selected node context and mandate profile";
		}
		if (mode === "compare") {
			return compareSelection.length >= 2
				? `${compareSelection.length} managers loaded for overlap analysis`
				: "Select managers to unlock overlap and allocation studies";
		}
		return selectedHolding ? `${cleanLabel(selectedHolding.issuer_name)} ownership timeline` : "CUSIP ownership timeline";
	}

	$effect(() => {
		const id = fundId;
		if (!id) {
			holdings = [];
			reveal = null;
			selectedCusip = null;
			graph = null;
			selectedHolderId = null;
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
				const [holdingsResponse, revealResponse] = await Promise.all([
					fetch(`${apiBase}/wealth/discovery/funds/${encodeURIComponent(id)}/analysis/holdings/top`, {
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
				if (!holdingsResponse.ok) {
					throw new Error(`Holdings analysis fetch failed: HTTP ${holdingsResponse.status}`);
				}
				const holdingsPayload = (await holdingsResponse.json()) as HoldingsPayload;
				const revealPayload =
					revealResponse && revealResponse.ok ? ((await revealResponse.json()) as RevealPayload) : null;
				if (cancelled) return;
				holdings = holdingsPayload.top_holdings ?? [];
				reveal = revealPayload;
				selectedCusip = holdingsPayload.top_holdings?.[0]?.cusip ?? null;
				selectedHolderId = null;
				sourceMode = "all";
			} catch (fetchError: unknown) {
				if (cancelled) return;
				if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
				error = fetchError instanceof Error ? fetchError.message : "Failed to load holdings network.";
				holdings = [];
				reveal = null;
				selectedCusip = null;
				selectedHolderId = null;
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		return () => {
			cancelled = true;
			controller.abort();
		};
	});

	$effect(() => {
		const cusip = selectedCusip;
		if (!cusip) {
			graph = null;
			graphLoading = false;
			return;
		}

		let cancelled = false;
		const controller = new AbortController();
		graphLoading = true;

		(async () => {
			try {
				const token = await getToken();
				const response = await fetch(
					`${apiBase}/wealth/discovery/holdings/${encodeURIComponent(cusip)}/reverse-lookup?limit=36`,
					{
						headers: { Authorization: `Bearer ${token}` },
						signal: controller.signal,
					},
				);
				if (!response.ok) {
					throw new Error(`Reverse lookup fetch failed: HTTP ${response.status}`);
				}
				const payload = (await response.json()) as ReverseLookupPayload;
				if (cancelled) return;
				graph = payload;
			} catch (fetchError: unknown) {
				if (cancelled) return;
				if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
				graph = null;
				error = fetchError instanceof Error ? fetchError.message : "Failed to load reverse lookup.";
			} finally {
				if (!cancelled) graphLoading = false;
			}
		})();

		return () => {
			cancelled = true;
			controller.abort();
		};
	});

	const selectedHolding = $derived.by(() => holdings.find((holding) => holding.cusip === selectedCusip) ?? null);
	const tokens = $derived.by(() => terminalChartTokens());
	const activeLensLabel = $derived.by(() => lensLabel(lowerMode));
	const activeLensDescription = $derived.by(() => lensDescription(lowerMode));

	const reverseDisplayNodes = $derived.by<DisplayNode[]>(() =>
		(graph?.nodes ?? [])
			.filter((node) => node.category === "holder")
			.map((node) => ({
				id: node.id,
				displayId: node.id,
				name: node.name,
				source: node.source === "13f" ? "13f" : "nport",
				value: node.value ?? null,
				managerCik: node.id,
			})),
	);

	const curatedDisplayNodes = $derived.by<DisplayNode[]>(() => {
		const cusip = selectedCusip;
		const currentReveal = reveal;
		if (!cusip || !currentReveal) return [];
		return currentReveal.institutions
			.map((institution) => ({
				id: `curated:${institution.institution_id}`,
				displayId: institution.cik ?? `curated:${institution.institution_id}`,
				name: institution.name,
				source: "curated" as const,
				value: currentReveal.overlap_matrix?.[institution.institution_id]?.[cusip] ?? 0,
				category: institution.category,
				country: institution.country ?? null,
				managerCik: institution.cik ?? null,
			}))
			.filter((institution) => institution.value > 0);
	});

	const visibleHolderNodes = $derived.by<DisplayNode[]>(() => {
		const merged = [...reverseDisplayNodes, ...curatedDisplayNodes];
		if (sourceMode === "all") return merged;
		return merged.filter((node) => node.source === sourceMode);
	});

	$effect(() => {
		const visible = visibleHolderNodes;
		if (visible.length === 0) {
			selectedHolderId = null;
			return;
		}
		if (!selectedHolderId || !visible.some((node) => node.id === selectedHolderId)) {
			selectedHolderId = visible[0]?.id ?? null;
		}
	});

	const selectedHolder = $derived.by(() => visibleHolderNodes.find((node) => node.id === selectedHolderId) ?? null);
	const selectableCompareNodes = $derived.by(() =>
		visibleHolderNodes.filter((node) => node.source !== "nport" && node.managerCik),
	);
	const anchorNode = $derived.by(
		() => selectableCompareNodes.find((node) => node.managerCik === anchorManagerCik) ?? null,
	);

	$effect(() => {
		const validCiks = new Set(selectableCompareNodes.map((node) => node.managerCik).filter(Boolean) as string[]);
		if (anchorManagerCik && !validCiks.has(anchorManagerCik)) {
			anchorManagerCik = compareSelection[0] ?? null;
			return;
		}
		if (!anchorManagerCik && compareSelection.length > 0) {
			anchorManagerCik = compareSelection[0] ?? null;
		}
	});

	const graphOption = $derived.by(() => {
		const activeSelection = new Set(compareSelection);
		const anchorCik = anchorManagerCik;
		const priorityLabelIds = new Set<string>([
			selectedCusip ?? "",
			selectedHolderId ?? "",
			...topGraphHolders.slice(0, 4).map((holder) => holder.id),
			...visibleHolderNodes
				.filter((node) => node.managerCik != null && activeSelection.has(node.managerCik))
				.map((node) => node.id),
			...visibleHolderNodes
				.filter((node) => node.managerCik != null && node.managerCik === anchorCik)
				.map((node) => node.id),
		]);
		const centerNode = selectedCusip && selectedHolding
			? [{
				id: selectedCusip,
				name: selectedHolding.issuer_name,
				value: selectedHolding.market_value ?? undefined,
				source: "holding",
				symbolSize: 42,
				itemStyle: {
					color: tokens.amber,
					borderColor: tokens.text,
					borderWidth: 2,
				},
			}]
			: [];

		const nodes = [
			...centerNode,
			...visibleHolderNodes.map((node) => ({
				isAnchor: node.managerCik != null && node.managerCik === anchorCik,
				isCompared: node.managerCik != null && activeSelection.has(node.managerCik),
				id: node.id,
				name: node.name,
				shortName: shortenEntityLabel(node.name, node.id === selectedHolderId ? 24 : 18),
				value: node.value ?? undefined,
				source: node.source,
				managerCik: node.managerCik,
				categoryLabel: node.category,
				country: node.country,
				symbolSize:
					node.id === selectedHolderId
						? 34
						: node.managerCik != null && node.managerCik === anchorCik
							? 30
							: node.managerCik != null && activeSelection.has(node.managerCik)
								? 27
								: node.source === "curated"
									? 24
									: 20,
				itemStyle: {
					color:
						node.managerCik != null && node.managerCik === anchorCik
							? tokens.amber
							: node.source === "13f"
								? tokens.violet
								: node.source === "curated"
									? tokens.amber
									: tokens.cyan,
					borderColor:
						node.id === selectedHolderId || (node.managerCik != null && activeSelection.has(node.managerCik))
							? tokens.text
							: tokens.grid,
					borderWidth:
						node.id === selectedHolderId
							? 2.5
							: node.managerCik != null && activeSelection.has(node.managerCik)
								? 2
								: 1,
					shadowBlur: node.managerCik != null && activeSelection.has(node.managerCik) ? 12 : 0,
					shadowColor:
						node.managerCik != null && node.managerCik === anchorCik ? tokens.amber : "transparent",
					opacity:
						activeSelection.size === 0 || (node.managerCik != null && activeSelection.has(node.managerCik))
							? 1
							: 0.55,
				},
			})),
		];

		const baseEdges = visibleHolderNodes.map((node) => ({
			source: node.id,
			target: selectedCusip,
			lineStyle: {
				color:
					node.managerCik != null && node.managerCik === anchorCik
						? tokens.amber
						: node.source === "curated"
							? tokens.amber
							: tokens.grid,
				width:
					node.id === selectedHolderId
						? 2.6
						: node.managerCik != null && activeSelection.has(node.managerCik)
							? 1.8
							: 1,
				opacity:
					activeSelection.size === 0 || (node.managerCik != null && activeSelection.has(node.managerCik))
						? 0.92
						: 0.38,
				curveness: node.source === "curated" ? 0.2 : 0.12,
			},
		}));

		const compareNodeMap = new Map(
			visibleHolderNodes
				.filter((node) => node.managerCik)
				.map((node) => [node.managerCik as string, node.id]),
		);

		const overlapEdges =
			managerCompare?.overlaps
				.filter((overlap) => compareNodeMap.has(overlap.cik_a) && compareNodeMap.has(overlap.cik_b))
				.map((overlap) => {
					const isAnchorLink = overlap.cik_a === anchorCik || overlap.cik_b === anchorCik;
					return {
						source: compareNodeMap.get(overlap.cik_a),
						target: compareNodeMap.get(overlap.cik_b),
						lineStyle: {
							color: isAnchorLink ? tokens.amber : tokens.cyan,
							width: 1 + overlap.overlap_pct * 9,
							opacity: isAnchorLink ? 0.95 : 0.35 + overlap.overlap_pct * 0.45,
							type: "dashed",
							curveness: 0.18,
						},
						value: overlap.overlap_pct,
						label: {
							show: overlap.overlap_pct >= 0.3,
							formatter: percent(overlap.overlap_pct, 0),
							color: isAnchorLink ? tokens.amber : tokens.secondary,
							fontSize: 8,
						},
					};
				}) ?? [];

		const edges = [...baseEdges, ...overlapEdges];

		return {
			textStyle: { fontFamily: tokens.font, fontSize: 10 },
			tooltip: {
				backgroundColor: tokens.bg,
				borderColor: tokens.grid,
				borderWidth: 1,
				textStyle: { color: tokens.text, fontSize: 10 },
				formatter: (params: { dataType?: string; data?: { name?: string; value?: number; source?: string; managerCik?: string; categoryLabel?: string; country?: string } }) => {
					if (params.dataType === "edge") return "";
					const data = params.data ?? {};
					const source = data.source ? ` · ${sourceLabel(data.source as DisplayNode["source"])}` : "";
					const cik = data.managerCik ? `<br/>CIK ${data.managerCik}` : "";
					const category = data.categoryLabel ? `<br/>${cleanLabel(data.categoryLabel)}` : "";
					const country = data.country ? ` · ${cleanLabel(data.country)}` : "";
					const value = typeof data.value === "number" ? `<br/>${formatCompact(data.value)}` : "";
					return `<strong>${cleanLabel(data.name)}</strong>${source}${country}${cik}${category}${value}`;
				},
			},
			series: [
				{
					type: "graph",
					layout: "force",
					roam: true,
					draggable: true,
					left: 24,
					right: 24,
					top: 18,
					bottom: 18,
					force: { repulsion: 220, edgeLength: [72, 168], gravity: 0.06 },
					label: {
						show: true,
						position: "right",
						color: tokens.secondary,
						fontSize: 9,
						width: 132,
						overflow: "truncate",
						formatter: (params: { data?: { id?: string; name?: string; shortName?: string; isAnchor?: boolean; isCompared?: boolean } }) => {
							if (!params.data?.id || !priorityLabelIds.has(params.data.id)) return "";
							const name = params.data.shortName ?? shortenEntityLabel(params.data?.name, 18);
							if (params.data?.isAnchor) return `${name} [A]`;
							if (params.data?.isCompared) return `${name} [C]`;
							return name;
						},
					},
					labelLayout: { hideOverlap: true, moveOverlap: "shiftY" },
					data: nodes,
					edges,
					emphasis: {
						focus: "adjacency",
						lineStyle: { color: tokens.amber, width: 2 },
					},
				},
			],
		};
	});

	const topGraphHolders = $derived.by(() =>
		[...visibleHolderNodes]
			.sort((left, right) => (right.value ?? 0) - (left.value ?? 0))
			.slice(0, 10),
	);

	function toggleCompareSelection(node: DisplayNode): void {
		const cik = node.managerCik;
		if (!cik) return;
		if (compareSelection.includes(cik)) {
			compareSelection = compareSelection.filter((item) => item !== cik);
			if (anchorManagerCik === cik) {
				anchorManagerCik = compareSelection.filter((item) => item !== cik)[0] ?? null;
			}
			return;
		}
		if (compareSelection.length >= 5) {
			const next = [...compareSelection.slice(1), cik];
			compareSelection = next;
			if (!anchorManagerCik || !next.includes(anchorManagerCik)) {
				anchorManagerCik = next[0] ?? null;
			}
			return;
		}
		compareSelection = [...compareSelection, cik];
		if (!anchorManagerCik) anchorManagerCik = cik;
	}

	function setAnchor(cik: string | null): void {
		anchorManagerCik = cik;
	}

	$effect(() => {
		if (compareSelection.length >= 2 && lowerMode === "entity") {
			lowerMode = "compare";
		}
	});

	$effect(() => {
		const holder = selectedHolder;
		if (!holder?.managerCik || holder.source === "nport") return;
		if (compareSelection.includes(holder.managerCik)) return;
		compareSelection = [...compareSelection, holder.managerCik].slice(-5);
	});

	$effect(() => {
		const validCiks = new Set(selectableCompareNodes.map((node) => node.managerCik).filter(Boolean) as string[]);
		const nextSelection = compareSelection.filter((cik) => validCiks.has(cik));
		if (nextSelection.length !== compareSelection.length) {
			compareSelection = nextSelection;
		}
	});

	const historyBars = $derived.by(() => {
		const points = ownershipHistory?.quarters ?? [];
		const max = Math.max(...points.map((point) => point.total_market_value), 1);
		return points.map((point) => ({
			...point,
			width: `${(point.total_market_value / max) * 100}%`,
		}));
	});

	$effect(() => {
		const chart = graphChart;
		if (!chart) return;

		const handler = (params: unknown) => {
			const targetId =
				typeof params === "object" && params !== null && "data" in params
					? ((params as { data?: { id?: string | null } }).data?.id ?? null)
					: null;
			if (!targetId || targetId === selectedCusip) return;
			selectedHolderId = targetId;
		};

		chart.on("click", handler);
		return () => {
			chart.off("click", handler);
		};
	});

	$effect(() => {
		if (compareSelection.length < 2) {
			managerCompare = null;
			compareLoading = false;
			return;
		}

		let cancelled = false;
		const controller = new AbortController();
		compareLoading = true;

		(async () => {
			try {
				const token = await getToken();
				const search = compareSelection
					.map((cik) => `ciks=${encodeURIComponent(cik)}`)
					.join("&");
				const response = await fetch(`${apiBase}/sec/managers/compare?${search}`, {
					headers: { Authorization: `Bearer ${token}` },
					signal: controller.signal,
				});
				if (!response.ok) {
					throw new Error(`Manager compare failed: HTTP ${response.status}`);
				}
				const payload = (await response.json()) as ManagerComparePayload;
				if (cancelled) return;
				managerCompare = payload;
			} catch (fetchError: unknown) {
				if (cancelled) return;
				if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
				managerCompare = null;
			} finally {
				if (!cancelled) compareLoading = false;
			}
		})();

		return () => {
			cancelled = true;
			controller.abort();
		};
	});

	$effect(() => {
		const holder = selectedHolder;
		const cusip = selectedCusip;
		if (!holder || !cusip) {
			managerDetail = null;
			fundDetail = null;
			fundBreakdown = null;
			ownershipHistory = null;
			inspectorLoading = false;
			return;
		}

		let cancelled = false;
		const controller = new AbortController();
		inspectorLoading = true;

		(async () => {
			try {
				const token = await getToken();
				const headers = { Authorization: `Bearer ${token}` };

				const historyRequest = fetch(
					`${apiBase}/sec/holdings/history?cusip=${encodeURIComponent(cusip)}`,
					{ headers, signal: controller.signal },
				).catch(() => null);

				if (holder.source === "nport") {
					const [fundResponse, historyResponse] = await Promise.all([
						holder.managerCik
							? fetch(`${apiBase}/sec/funds/${encodeURIComponent(holder.managerCik)}`, {
								headers,
								signal: controller.signal,
							}).catch(() => null)
							: Promise.resolve(null),
						historyRequest,
					]);

					if (!cancelled) {
						fundDetail = fundResponse && fundResponse.ok ? ((await fundResponse.json()) as FundDetail) : null;
						managerDetail = null;
						fundBreakdown = null;
						ownershipHistory =
							historyResponse && historyResponse.ok ? ((await historyResponse.json()) as OwnershipHistory) : null;
					}
					return;
				}

				const [managerResponse, historyResponse] = await Promise.all([
					holder.managerCik
						? fetch(`${apiBase}/sec/managers/${encodeURIComponent(holder.managerCik)}`, {
							headers,
							signal: controller.signal,
						}).catch(() => null)
						: Promise.resolve(null),
					historyRequest,
				]);

				const detail =
					managerResponse && managerResponse.ok ? ((await managerResponse.json()) as ManagerDetail) : null;
				let breakdown: FundBreakdown | null = null;
				if (detail?.crd_number) {
					const breakdownResponse = await fetch(
						`${apiBase}/sec/managers/${encodeURIComponent(detail.crd_number)}/funds`,
						{ headers, signal: controller.signal },
					).catch(() => null);
					breakdown =
						breakdownResponse && breakdownResponse.ok
							? ((await breakdownResponse.json()) as FundBreakdown)
							: null;
				}

				if (cancelled) return;
				managerDetail = detail;
				fundBreakdown = breakdown;
				fundDetail = null;
				ownershipHistory =
					historyResponse && historyResponse.ok ? ((await historyResponse.json()) as OwnershipHistory) : null;
			} catch (fetchError: unknown) {
				if (cancelled) return;
				if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
				managerDetail = null;
				fundDetail = null;
				fundBreakdown = null;
				ownershipHistory = null;
			} finally {
				if (!cancelled) inspectorLoading = false;
			}
		})();

		return () => {
			cancelled = true;
			controller.abort();
		};
	});

	const compareManagers = $derived.by(() => managerCompare?.managers ?? []);
	const compareOverlapRows = $derived.by(() =>
		(managerCompare?.overlaps ?? [])
			.map((item) => {
				const left = compareManagers.find((manager) => manager.cik === item.cik_a);
				const right = compareManagers.find((manager) => manager.cik === item.cik_b);
				return {
					key: `${item.cik_a}:${item.cik_b}`,
					left: left?.firm_name ?? item.cik_a,
					right: right?.firm_name ?? item.cik_b,
					overlap: item.overlap_pct,
				};
			})
			.sort((left, right) => right.overlap - left.overlap),
	);

	const sectorUniverse = $derived.by(() => {
		const sectors = new Set<string>();
		for (const allocation of Object.values(managerCompare?.sector_allocations ?? {})) {
			for (const sector of Object.keys(allocation)) sectors.add(sector);
		}
		return [...sectors].slice(0, 10);
	});

	const compareHhiRows = $derived.by(() =>
		compareManagers
			.map((manager) => ({
				cik: manager.cik ?? manager.crd_number,
				name: manager.firm_name,
				hhi: managerCompare?.hhi_scores?.[manager.cik ?? ""] ?? null,
				sectorMix: managerCompare?.sector_allocations?.[manager.cik ?? ""] ?? {},
			}))
			.filter((manager) => manager.cik),
	);

	const overlapMatrixOption = $derived.by(() => {
		const managers = compareManagers.filter((manager) => manager.cik);
		const labels = managers.map((manager) => manager.firm_name);
		const lookup = new Map(compareOverlapRows.map((row) => [`${row.left}:::${row.right}`, row.overlap]));
		const points: Array<[number, number, number]> = [];
		managers.forEach((rowManager, y) => {
			managers.forEach((colManager, x) => {
				if (rowManager.cik === colManager.cik) {
					points.push([x, y, 1]);
					return;
				}
				const directKey = `${rowManager.firm_name}:::${colManager.firm_name}`;
				const reverseKey = `${colManager.firm_name}:::${rowManager.firm_name}`;
				points.push([x, y, lookup.get(directKey) ?? lookup.get(reverseKey) ?? 0]);
			});
		});

		return {
			textStyle: { fontFamily: tokens.font, fontSize: 9 },
			tooltip: {
				backgroundColor: tokens.bg,
				borderColor: tokens.grid,
				borderWidth: 1,
				textStyle: { color: tokens.text, fontSize: 10 },
				formatter: (params: { data: [number, number, number] }) => {
					const left = cleanLabel(labels[params.data[1]]);
					const right = cleanLabel(labels[params.data[0]]);
					return `<strong>${left}</strong><br/>${right}<br/>OVERLAP ${percent(params.data[2], 1)}`;
				},
			},
			grid: { left: 120, right: 18, top: 18, bottom: 72 },
			xAxis: {
				type: "category",
				data: labels.map((label) => {
					const next = cleanLabel(label);
					return next.length > 18 ? `${next.slice(0, 17)}…` : next;
				}),
				axisLabel: { color: tokens.muted, rotate: 28, interval: 0, fontSize: 9 },
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			yAxis: {
				type: "category",
				data: labels.map((label) => {
					const next = cleanLabel(label);
					return next.length > 20 ? `${next.slice(0, 19)}…` : next;
				}),
				axisLabel: { color: tokens.muted, fontSize: 9 },
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			visualMap: {
				min: 0,
				max: 1,
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

	const sectorAllocationOption = $derived.by(() => {
		const managers = compareHhiRows;
		const sectors = sectorUniverse;
		const palette = [tokens.cyan, tokens.violet, tokens.amber, tokens.success, tokens.error, tokens.secondary, tokens.cyanDim, "#4f7cff", "#ff8ac5", "#7ae582"];

		return {
			textStyle: { fontFamily: tokens.font, fontSize: 9 },
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				backgroundColor: tokens.bg,
				borderColor: tokens.grid,
				borderWidth: 1,
				textStyle: { color: tokens.text, fontSize: 10 },
				formatter: (params: Array<{ seriesName: string; data: number; axisValueLabel?: string }>) => {
					if (!params.length) return "";
					const managerName = cleanLabel(params[0]?.axisValueLabel ?? "");
					const rows = params
						.filter((item) => item.data > 0)
						.sort((a, b) => b.data - a.data)
						.map((item) => `${cleanLabel(item.seriesName)}: ${percent(item.data, 0)}`)
						.join("<br/>");
					return `<strong>${managerName}</strong><br/>${rows}`;
				},
			},
			grid: { left: 90, right: 18, top: 20, bottom: 18, containLabel: true },
			xAxis: {
				type: "value",
				max: 1,
				axisLabel: { color: tokens.muted, formatter: (value: number) => percent(value, 0) },
				axisLine: { lineStyle: { color: tokens.grid } },
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
			},
			yAxis: {
				type: "category",
				data: managers.map((manager) => {
					const next = cleanLabel(manager.name);
					return next.length > 18 ? `${next.slice(0, 17)}…` : next;
				}),
				axisLabel: { color: tokens.muted, fontSize: 9 },
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			series: sectors.map((sector, index) => ({
				name: cleanLabel(sector),
				type: "bar",
				stack: "sector",
				barMaxWidth: 16,
				itemStyle: { color: palette[index % palette.length] },
				data: managers.map((manager) => manager.sectorMix[sector] ?? 0),
			})),
		};
	});
</script>

<div class="hn-root">
	<div class="hn-header">
		<div class="hn-title-block">
			<div class="hn-title">OWNERSHIP NETWORK</div>
			<div class="hn-subtitle">{ticker ?? "—"} · {cleanLabel(label)}</div>
		</div>
		<div class="hn-header-right">
			<div class="hn-source-bar">
				{#each ([
					{ key: "all", label: sourceFilterLabel("all") },
					{ key: "13f", label: sourceFilterLabel("13f") },
					{ key: "nport", label: sourceFilterLabel("nport") },
					{ key: "curated", label: sourceFilterLabel("curated") },
				] as const) as mode (mode.key)}
					<button
						type="button"
						class="hn-source-btn"
						class:hn-source-btn--active={sourceMode === mode.key}
						onclick={() => (sourceMode = mode.key)}
					>
						{mode.label}
					</button>
				{/each}
			</div>
			{#if selectedHolding}
				<div class="hn-chip">{selectedHolding.cusip}</div>
			{/if}
		</div>
	</div>

	{#if loading}
		<div class="hn-message">Loading holdings network...</div>
	{:else if error}
		<div class="hn-message hn-message--error">{error}</div>
	{:else if holdings.length === 0}
		<div class="hn-message">No holdings disclosure is available for reverse lookup.</div>
	{:else}
		<div class="hn-grid">
			<section class="hn-panel hn-panel--rail">
				<div class="hn-panel-head">
					<span>REVERSE LOOKUP SEED</span>
					<span>{holdings.length} HOLDINGS</span>
				</div>
				<div class="hn-list">
					{#each holdings.slice(0, 14) as holding (holding.cusip)}
						<button
							type="button"
							class="hn-row"
							class:hn-row--active={selectedCusip === holding.cusip}
							onclick={() => {
								selectedCusip = holding.cusip;
								selectedHolderId = null;
							}}
						>
							<div class="hn-row-main">
								<strong>{cleanLabel(holding.issuer_name)}</strong>
								<span>{cleanLabel(holding.sector)}</span>
							</div>
							<div class="hn-row-meta">
								<span>{percent(holding.weight, 1)}</span>
								<span>{holding.cusip}</span>
							</div>
						</button>
					{/each}
				</div>
				<div class="hn-stack">
					<div class="hn-subsection">
						<div class="hn-subtitle-row">COMPARE MANAGERS</div>
						{#if selectableCompareNodes.length > 0}
							<div class="hn-compare-picks">
								{#each selectableCompareNodes.slice(0, 12) as node (node.id)}
									<button
										type="button"
										class="hn-compare-chip"
										class:hn-compare-chip--active={node.managerCik != null && compareSelection.includes(node.managerCik)}
										onclick={() => toggleCompareSelection(node)}
									>
										<span>{node.name}</span>
										<strong>{sourceLabel(node.source)}</strong>
									</button>
								{/each}
							</div>
							{#if compareSelection.length > 0}
								<div class="hn-anchor-strip">
									<span class="hn-toolbar-label">ANCHOR</span>
									<div class="hn-anchor-picks">
										{#each compareManagers as manager (manager.cik ?? manager.crd_number)}
											{#if manager.cik}
												<button
													type="button"
													class="hn-anchor-chip"
													class:hn-anchor-chip--active={anchorManagerCik === manager.cik}
													onclick={() => setAnchor(manager.cik)}
												>
													<span>{cleanLabel(manager.firm_name)}</span>
												</button>
											{/if}
										{/each}
										{#if compareManagers.length === 0}
											{#each selectableCompareNodes.filter((node) => node.managerCik != null && compareSelection.includes(node.managerCik)).slice(0, 5) as node (node.id)}
												<button
													type="button"
													class="hn-anchor-chip"
													class:hn-anchor-chip--active={anchorManagerCik === node.managerCik}
													onclick={() => setAnchor(node.managerCik ?? null)}
												>
													<span>{cleanLabel(node.name)}</span>
												</button>
											{/each}
										{/if}
									</div>
								</div>
							{/if}
						{:else}
							<div class="hn-empty-note">No comparable manager nodes are available under the active source filter.</div>
						{/if}
					</div>
				</div>
			</section>

			<section class="hn-panel hn-panel--stage">
				<div class="hn-panel-head">
					<span>LES MIS MAP</span>
					<span>{graphLoading ? "LOADING" : `${visibleHolderNodes.length} VISIBLE NODES`}</span>
				</div>
				<div class="hn-graph-toolbar">
					<div class="hn-toolbar-block">
						<span class="hn-toolbar-label">ANCHOR</span>
						<strong>{anchorNode ? cleanLabel(anchorNode.name) : "AUTO"}</strong>
					</div>
					<div class="hn-toolbar-block">
						<span class="hn-toolbar-label">COMPARE SET</span>
						<strong>{compareSelection.length}/5</strong>
					</div>
					<div class="hn-toolbar-block">
						<span class="hn-toolbar-label">WEIGHTED LINKS</span>
						<strong>{managerCompare ? "ON" : "STANDBY"}</strong>
					</div>
				</div>
				<div class="hn-graph">
					{#if selectedCusip}
						<ChartContainer bind:chart={graphChart} option={graphOption} height={680} ariaLabel="Reverse lookup graph" />
					{:else}
						<div class="hn-message">Select a holding to render the reverse lookup graph.</div>
					{/if}
				</div>
				<div class="hn-holder-strip">
					{#each topGraphHolders as holder (holder.id)}
						<button
							type="button"
							class="hn-holder-chip"
							class:hn-holder-chip--active={selectedHolderId === holder.id}
							class:hn-holder-chip--compare={holder.managerCik != null && compareSelection.includes(holder.managerCik)}
							class:hn-holder-chip--anchor={holder.managerCik != null && anchorManagerCik === holder.managerCik}
							onclick={() => (selectedHolderId = holder.id)}
						>
							<span>{cleanLabel(holder.name)}</span>
							<strong>{sourceLabel(holder.source)}</strong>
						</button>
					{/each}
				</div>
				<div class="hn-stage-lower">
					<div class="hn-lower-shell">
						<div class="hn-lens-header">
							<div class="hn-lens-title">{activeLensLabel}</div>
							<div class="hn-lens-copy">{activeLensDescription}</div>
						</div>
						<div class="hn-lower-tabs">
							<button
								type="button"
								class="hn-lower-tab"
								class:hn-lower-tab--active={lowerMode === "entity"}
								onclick={() => (lowerMode = "entity")}
							>
								ANCHOR VIEW
							</button>
							<button
								type="button"
								class="hn-lower-tab"
								class:hn-lower-tab--active={lowerMode === "compare"}
								onclick={() => (lowerMode = "compare")}
							>
								MANAGER OVERLAP
							</button>
							<button
								type="button"
								class="hn-lower-tab"
								class:hn-lower-tab--active={lowerMode === "ownership"}
								onclick={() => (lowerMode = "ownership")}
							>
								MARKET OWNERSHIP
							</button>
						</div>
						<div class="hn-lower-panel">
							{#if lowerMode === "entity"}
								<div class="hn-lower-grid hn-lower-grid--entity">
									<div class="hn-stack">
										<div class="hn-subsection">
											<div class="hn-subtitle-row">MANAGER DRILL-DOWN</div>
											{#if selectedHolder}
								<div class="hn-insight-row">
									<div>
										<strong>{cleanLabel(selectedHolder.name)}</strong>
										<span>{sourceLabel(selectedHolder.source)}{selectedHolder.category ? ` · ${cleanLabel(selectedHolder.category)}` : ""}</span>
									</div>
									<span>{compactMoney(selectedHolder.value)}</span>
								</div>
												<div class="hn-insight-row">
													<div>
														<strong>CIK</strong>
														<span>{selectedHolder.managerCik ?? "UNMAPPED"}</span>
													</div>
													<span>{selectedHolder.country ?? "—"}</span>
												</div>
											{:else}
												<div class="hn-empty-note">Select a node in the graph or in the holder strip.</div>
											{/if}
										</div>

										<div class="hn-subsection">
											<div class="hn-subtitle-row">ENTITY PROFILE</div>
											{#if inspectorLoading}
												<div class="hn-empty-note">Loading entity profile...</div>
											{:else if fundDetail}
												<div class="hn-insight-row">
									<div>
										<strong>{cleanLabel(fundDetail.fund_name)}</strong>
										<span>{cleanLabel(fundDetail.fund_type)}</span>
									</div>
													<span>{fundDetail.total_assets != null ? compactMoney(fundDetail.total_assets) : "—"}</span>
												</div>
												<div class="hn-insight-row">
													<div>
														<strong>TICKER</strong>
														<span>{fundDetail.ticker ?? "—"}</span>
													</div>
													<span>{fundDetail.last_nport_date ?? "—"}</span>
												</div>
											{:else if managerDetail}
												<div class="hn-insight-row">
									<div>
										<strong>{cleanLabel(managerDetail.firm_name)}</strong>
										<span>{cleanLabel(managerDetail.registration_status ?? "REGISTERED")}</span>
									</div>
													<span>{managerDetail.aum_total != null ? compactMoney(managerDetail.aum_total) : "—"}</span>
												</div>
												<div class="hn-insight-row">
													<div>
														<strong>PORTFOLIO VALUE</strong>
														<span>{managerDetail.linked_13f_ciks?.length ? `${managerDetail.linked_13f_ciks.length} linked manager entities` : "direct coverage"}</span>
													</div>
													<span>{managerDetail.total_portfolio_value != null ? compactMoney(managerDetail.total_portfolio_value) : "—"}</span>
												</div>
												<div class="hn-insight-row">
									<div>
										<strong>HOLDINGS</strong>
										<span>{cleanLabel(managerDetail.state)} · {cleanLabel(managerDetail.country)}</span>
									</div>
													<span>{managerDetail.holdings_count != null ? formatNumber(managerDetail.holdings_count, 0) : "—"}</span>
												</div>
											{:else}
												<div class="hn-empty-note">No richer profile was resolved for the selected node.</div>
											{/if}
										</div>
									</div>

									<div class="hn-stack">
										<div class="hn-subsection">
											<div class="hn-subtitle-row">FUND / MANDATE MIX</div>
											{#if fundBreakdown?.breakdown?.length}
												{#each fundBreakdown.breakdown.slice(0, 6) as item (item.fund_type)}
													<div class="hn-insight-row">
														<div>
															<strong>{cleanLabel(item.fund_type)}</strong>
															<span>{percent(item.pct_of_total, 1)} OF TOTAL FUNDS</span>
														</div>
														<span>{formatNumber(item.fund_count, 0)}</span>
													</div>
												{/each}
											{:else}
												<div class="hn-empty-note">No manager fund breakdown available for this node.</div>
											{/if}
										</div>

										{#if selectedHolding}
											<div class="hn-footnote">
												<span>WEIGHT {percent(selectedHolding.weight, 1)}</span>
												<span>VALUE {selectedHolding.market_value != null ? formatCompact(selectedHolding.market_value) : "—"}</span>
											</div>
										{/if}
									</div>
								</div>
							{:else if lowerMode === "compare"}
								<div class="hn-lower-grid hn-lower-grid--compare">
									<div class="hn-stack">
										{#if compareSelection.length >= 2 && managerCompare}
											<div class="hn-compare-visuals">
												<div class="hn-visual-panel">
													<div class="hn-subtitle-row">OVERLAP MAP</div>
													<ChartContainer option={overlapMatrixOption} height={240} ariaLabel="Manager overlap heatmap" />
												</div>
												<div class="hn-visual-panel">
													<div class="hn-subtitle-row">SECTOR STACK</div>
													<ChartContainer option={sectorAllocationOption} height={240} ariaLabel="Manager sector allocation chart" />
												</div>
											</div>
										{:else}
											<div class="hn-subsection">
												<div class="hn-subtitle-row">COMPARE STATE</div>
												<div class="hn-empty-note">Select at least two managers to unlock visual comparison.</div>
											</div>
										{/if}
									</div>

									<div class="hn-stack">
										<div class="hn-subsection">
											<div class="hn-subtitle-row">OVERLAP / CONCENTRATION</div>
											{#if compareLoading}
												<div class="hn-empty-note">Running manager comparison...</div>
											{:else if compareSelection.length < 2}
												<div class="hn-empty-note">Select at least two managers to compute overlap and concentration.</div>
											{:else if managerCompare}
												<div class="hn-compare-summary">
													{#each compareHhiRows as row (row.cik)}
														<div class="hn-compare-card">
															<strong>{cleanLabel(row.name)}</strong>
															<span>HHI {row.hhi != null ? formatNumber(row.hhi, 2) : "—"}</span>
															<span>{Object.keys(row.sectorMix).length} sectors mapped</span>
														</div>
													{/each}
												</div>
												<div class="hn-compare-table">
													{#each compareOverlapRows as row (row.key)}
														<div class="hn-history-row">
															<span>{cleanLabel(row.left)} × {cleanLabel(row.right)}</span>
															<div class="hn-history-track">
																<div class="hn-history-fill hn-history-fill--amber" style={`width:${Math.max(4, row.overlap * 100)}%`}></div>
															</div>
															<span>{percent(row.overlap, 1)}</span>
														</div>
													{/each}
												</div>
											{:else}
												<div class="hn-empty-note">Manager comparison is unavailable for the current selection.</div>
											{/if}
										</div>

										<div class="hn-subsection">
											<div class="hn-subtitle-row">SECTOR ALLOCATION</div>
											{#if managerCompare && sectorUniverse.length > 0}
												<div class="hn-sector-grid">
													<div class="hn-sector-head">
														<span>MANAGER</span>
														{#each sectorUniverse as sector (sector)}
															<span>{cleanLabel(sector)}</span>
														{/each}
													</div>
													{#each compareHhiRows as row (row.cik)}
														<div class="hn-sector-row">
															<span class="hn-sector-manager">{cleanLabel(row.name)}</span>
															{#each sectorUniverse as sector (sector)}
																<span>{percent(row.sectorMix[sector] ?? null, 0)}</span>
															{/each}
														</div>
													{/each}
												</div>
											{:else}
												<div class="hn-empty-note">Sector allocation will appear here once a manager comparison is loaded.</div>
											{/if}
										</div>
									</div>
								</div>
							{:else}
								<div class="hn-lower-grid hn-lower-grid--ownership">
									<div class="hn-subsection">
										<div class="hn-subtitle-row">OWNERSHIP HISTORY</div>
										{#if historyBars.length > 0}
											{#each historyBars as point (point.quarter)}
												<div class="hn-history-row">
													<span>{point.quarter}</span>
													<div class="hn-history-track">
														<div class="hn-history-fill" style={`width:${point.width}`}></div>
													</div>
													<span>{formatNumber(point.total_holders, 0)}</span>
												</div>
											{/each}
										{:else}
											<div class="hn-empty-note">No ownership history was returned for the selected CUSIP.</div>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					</div>
				</div>
			</section>
		</div>
	{/if}
</div>

<style>
	.hn-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-width: 0;
		min-height: 0;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.hn-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
		padding: 10px 12px 8px;
		border-bottom: var(--terminal-border-hairline);
	}

	.hn-header-right,
	.hn-title-block {
		display: flex;
		align-items: flex-end;
		gap: 12px;
		min-width: 0;
	}

	.hn-title-block {
		flex-direction: column;
		align-items: flex-start;
		gap: 3px;
	}

	.hn-title,
	.hn-panel-head span:first-child,
	.hn-subtitle-row {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
	}

	.hn-subtitle,
	.hn-panel-head span:last-child,
	.hn-chip,
	.hn-row-main span,
	.hn-row-meta span,
	.hn-insight-row span,
	.hn-footnote,
	.hn-holder-chip span,
	.hn-history-row span {
		color: var(--terminal-fg-muted);
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		font-variant-numeric: tabular-nums;
	}

	.hn-chip {
		padding: 3px 8px;
		border: 1px solid var(--terminal-accent-violet);
		color: var(--terminal-accent-violet);
	}

	.hn-source-bar {
		display: flex;
		gap: 6px;
	}

	.hn-source-btn {
		height: 22px;
		padding: 0 9px;
		border: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		color: var(--terminal-fg-secondary);
		font-family: inherit;
		font-size: 9px;
		letter-spacing: 0.08em;
		cursor: pointer;
	}

	.hn-source-btn--active {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.hn-message,
	.hn-empty-note {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 24px;
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
		text-align: center;
	}

	.hn-message {
		height: 100%;
	}

	.hn-message--error {
		color: var(--terminal-status-error);
	}

	.hn-grid {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: 320px minmax(0, 1fr);
		gap: 1px;
		background: var(--terminal-fg-disabled);
	}

	.hn-panel {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		background: var(--terminal-bg-panel);
	}

	.hn-panel-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 8px 10px 6px;
		border-bottom: var(--terminal-border-hairline);
	}

	.hn-list,
	.hn-stack {
		overflow: auto;
		min-height: 0;
	}

	.hn-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		width: 100%;
		padding: 9px 10px;
		border: none;
		border-bottom: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		color: inherit;
		text-align: left;
		cursor: pointer;
		font-family: inherit;
	}

	.hn-row:hover,
	.hn-row--active {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent);
	}

	.hn-row-main,
	.hn-row-meta,
	.hn-insight-row > div {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.hn-row-main strong,
	.hn-insight-row strong,
	.hn-holder-chip strong {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
	}

	.hn-row-meta {
		align-items: flex-end;
	}

	.hn-panel--stage {
		min-height: 980px;
	}

	.hn-graph {
		flex: 1;
		min-height: 680px;
		padding: 10px 12px 8px;
		position: relative;
		overflow: hidden;
	}

	.hn-stage-lower {
		display: flex;
		flex-direction: column;
		border-top: 1px solid var(--terminal-fg-disabled);
		min-height: 0;
	}

	.hn-lower-shell {
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--terminal-bg-panel);
	}

	.hn-lower-tabs {
		display: flex;
		align-items: center;
		gap: 1px;
		padding: 0 10px;
		background: var(--terminal-fg-disabled);
		border-bottom: 1px solid var(--terminal-fg-disabled);
	}

	.hn-lower-tab {
		height: 28px;
		padding: 0 12px;
		border: none;
		background: var(--terminal-bg-panel);
		color: var(--terminal-fg-tertiary);
		font-family: inherit;
		font-size: 9px;
		letter-spacing: 0.1em;
		cursor: pointer;
	}

	.hn-lower-tab--active {
		color: var(--terminal-accent-amber);
		box-shadow: inset 0 -2px 0 var(--terminal-accent-amber);
	}

	.hn-lower-panel {
		display: flex;
		flex: 1;
		min-height: 0;
		background: var(--terminal-bg-panel);
	}

	.hn-lower-grid {
		display: grid;
		flex: 1;
		min-height: 0;
		gap: 1px;
		background: var(--terminal-fg-disabled);
	}

	.hn-lower-grid--entity,
	.hn-lower-grid--compare {
		grid-template-columns: minmax(320px, 0.92fr) minmax(360px, 1.08fr);
	}

	.hn-lower-grid--ownership {
		grid-template-columns: 1fr;
	}

	.hn-graph-toolbar {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 1px;
		border-bottom: 1px solid var(--terminal-fg-disabled);
		background: var(--terminal-fg-disabled);
	}

	.hn-toolbar-block {
		display: flex;
		flex-direction: column;
		gap: 3px;
		padding: 7px 10px;
		background: var(--terminal-bg-panel);
		min-width: 0;
	}

	.hn-toolbar-label {
		color: var(--terminal-fg-muted);
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.hn-toolbar-block strong {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-10);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.hn-holder-strip {
		display: flex;
		gap: 6px;
		padding: 0 10px 10px;
		overflow-x: auto;
		border-top: var(--terminal-border-hairline);
	}

	.hn-holder-chip {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 6px 9px;
		border: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		font-family: inherit;
		white-space: nowrap;
		cursor: pointer;
	}

	.hn-holder-chip--active {
		border-color: var(--terminal-accent-amber);
		background: color-mix(in srgb, var(--terminal-accent-amber) 10%, transparent);
	}

	.hn-holder-chip--compare {
		border-color: var(--terminal-accent-cyan);
	}

	.hn-holder-chip--anchor {
		border-color: var(--terminal-accent-amber);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--terminal-accent-amber) 45%, transparent);
	}

	.hn-compare-visuals {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		background: var(--terminal-fg-disabled);
	}

	.hn-visual-panel {
		display: flex;
		flex-direction: column;
		padding: 8px 10px 10px;
		background: var(--terminal-bg-panel);
	}

	.hn-compare-picks {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.hn-compare-chip {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 6px 9px;
		border: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		font-family: inherit;
		cursor: pointer;
	}

	.hn-compare-chip--active {
		border-color: var(--terminal-accent-cyan);
		background: color-mix(in srgb, var(--terminal-accent-cyan) 12%, transparent);
	}

	.hn-anchor-strip {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding-top: 8px;
	}

	.hn-anchor-picks {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.hn-anchor-chip {
		display: inline-flex;
		align-items: center;
		padding: 5px 8px;
		border: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		font-family: inherit;
		font-size: 9px;
		letter-spacing: 0.06em;
		color: var(--terminal-fg-secondary);
		cursor: pointer;
	}

	.hn-anchor-chip--active {
		border-color: var(--terminal-accent-amber);
		background: color-mix(in srgb, var(--terminal-accent-amber) 12%, transparent);
		color: var(--terminal-accent-amber);
	}

	.hn-stack {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--terminal-fg-disabled);
		min-width: 0;
		min-height: 0;
	}

	.hn-subsection {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 10px;
		background: var(--terminal-bg-panel);
		min-width: 0;
	}

	.hn-insight-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		align-items: center;
		padding: 8px 0;
		border-bottom: 1px solid var(--terminal-fg-disabled);
	}

	.hn-history-row {
		display: grid;
		grid-template-columns: 80px minmax(0, 1fr) 28px;
		gap: 10px;
		align-items: center;
		padding: 7px 0;
	}

	.hn-history-track {
		height: 10px;
		border: 1px solid var(--terminal-fg-disabled);
		background: var(--terminal-bg-panel-raised);
	}

	.hn-history-fill {
		height: 100%;
		background: linear-gradient(90deg, var(--terminal-accent-violet), var(--terminal-accent-cyan));
	}

	.hn-history-fill--amber {
		background: linear-gradient(90deg, var(--terminal-accent-violet), var(--terminal-accent-amber));
	}

	.hn-compare-summary {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 6px;
		margin-bottom: 10px;
	}

	.hn-compare-card {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 8px;
		border: 1px solid var(--terminal-fg-disabled);
		background: var(--terminal-bg-panel-raised);
	}

	.hn-compare-card strong,
	.hn-sector-manager {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-10);
	}

	.hn-compare-table {
		display: flex;
		flex-direction: column;
	}

	.hn-sector-grid {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--terminal-fg-disabled);
	}

	.hn-sector-head,
	.hn-sector-row {
		display: grid;
		grid-template-columns: 120px repeat(10, minmax(44px, 1fr));
		gap: 6px;
		padding: 8px;
		align-items: center;
	}

	.hn-sector-head {
		border-bottom: 1px solid var(--terminal-fg-disabled);
		background: var(--terminal-bg-panel-raised);
	}

	.hn-sector-row {
		border-bottom: 1px solid var(--terminal-fg-disabled);
	}

	.hn-sector-row:last-child {
		border-bottom: none;
	}

	.hn-footnote {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		padding: 10px;
		background: var(--terminal-bg-panel);
		border-top: var(--terminal-border-hairline);
	}

	@media (max-width: 1480px) {
		.hn-grid {
			grid-template-columns: 290px minmax(0, 1fr);
		}
	}

	@media (max-width: 1320px) {
		.hn-lower-grid--entity,
		.hn-lower-grid--compare,
		.hn-compare-visuals {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 1080px) {
		.hn-graph-toolbar {
			grid-template-columns: 1fr;
		}
	}
</style>
