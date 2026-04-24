<script lang="ts">
	import { getContext, onDestroy } from "svelte";
	import TerminalAssetTree, { type TreeNode } from "./TerminalAssetTree.svelte";
	import TerminalReturnsRiskDeck from "./TerminalReturnsRiskDeck.svelte";
	import TerminalHoldingsGrid from "./TerminalHoldingsGrid.svelte";
	import TerminalPeerAnalysisPanel from "./TerminalPeerAnalysisPanel.svelte";
	import TerminalHoldingsNetwork from "./TerminalHoldingsNetwork.svelte";
	import TerminalRiskKpis from "./TerminalRiskKpis.svelte";
	import CorrelationHeatmap from "../CorrelationHeatmap.svelte";
	import RiskReturnScatter from "../RiskReturnScatter.svelte";
	import { createClientApiClient } from "../../../api/client";

	export type ResearchMode = "universe" | "fund" | "holdings" | "peers" | "network";

	interface Props {
		initialFundId?: string | null;
		initialMode?: ResearchMode;
	}

	interface ScatterResponse {
		instrument_ids: string[];
		names: string[];
		tickers: Array<string | null>;
		expected_returns: Array<number | null>;
		tail_risks: Array<number | null>;
		volatilities: Array<number | null>;
		strategies: string[];
		strategy_map: Record<string, string>;
		as_of_dates: Array<string | null>;
	}

	interface CorrelationResponse {
		labels: string[];
		historical_matrix: number[][];
		structural_matrix: number[][];
		regime_state_at_calc: string | null;
		effective_window_days: number;
		cache_key: string;
	}

	interface CorrelationAccepted {
		job_id: string;
		stream_url: string;
		status: "accepted";
		cache_key: string;
	}

	interface CatalogDetail {
		external_id: string;
		instrument_id: string | null;
		name: string;
		ticker: string | null;
		fund_type: string;
		aum: number | null;
	}

	let { initialFundId = null, initialMode = "universe" }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
	const apiOrigin = apiBase.replace(/\/api\/v1$/, "");

	let activeMode = $state<ResearchMode>("universe");
	let selectedNode = $state<TreeNode | null>(null);
	let hydratingSelection = $state(false);
	let selectionError = $state<string | null>(null);

	let scatter = $state<ScatterResponse | null>(null);
	let correlation = $state<CorrelationResponse | null>(null);
	let correlationMode = $state<"structural" | "historical">("structural");
	let scatterLoading = $state(false);
	let correlationLoading = $state(false);
	let scatterError = $state<string | null>(null);
	let correlationError = $state<string | null>(null);
	let scatterController = $state<AbortController | null>(null);
	let correlationController = $state<AbortController | null>(null);
	let scatterInflight = $state(false);
	let correlationInflight = $state(false);
	let universeLoaded = $state(false);
	let universeAttempted = $state(false);

	const selectedId = $derived(selectedNode?.id ?? null);
	const titleLabel = $derived(selectedNode?.label ?? "Research Terminal");
	const tickerLabel = $derived(selectedNode?.ticker ?? "—");
	const instrumentId = $derived(selectedNode?.instrumentId ?? null);
	const showKpiRail = $derived(activeMode !== "network");
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
	const selectedModeTitle = $derived.by(() => {
		if (activeMode === "universe") return "Universe Intelligence";
		if (activeMode === "fund") return "Returns & Risk";
		if (activeMode === "holdings") return "Holdings Intelligence";
		if (activeMode === "peers") return "Peer Analysis";
		return "Ownership Network";
	});

	function handleSelect(node: TreeNode) {
		selectedNode = node;
		selectionError = null;
	}

	function buildStreamUrl(path: string): string {
		return path.startsWith("http") ? path : `${apiOrigin}${path}`;
	}

	function abortScatter() {
		scatterController?.abort();
		scatterController = null;
		scatterInflight = false;
	}

	function abortCorrelation() {
		correlationController?.abort();
		correlationController = null;
		correlationInflight = false;
	}

	async function readSseResult(url: string, signal: AbortSignal): Promise<CorrelationResponse> {
		const token = await getToken();
		const response = await fetch(url, {
			headers: {
				Authorization: `Bearer ${token}`,
				Accept: "text/event-stream",
			},
			signal,
		});
		if (!response.ok || !response.body) {
			throw new Error(`Correlation stream failed: HTTP ${response.status}`);
		}

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		let currentData = "";

		try {
			while (true) {
				if (signal.aborted) throw new DOMException("Aborted", "AbortError");
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("data:")) {
						currentData += `${currentData ? "\n" : ""}${line.slice(5).replace(/^ /, "")}`;
					} else if (line === "") {
						if (!currentData) continue;
						const event = JSON.parse(currentData) as {
							event?: string;
							result?: CorrelationResponse;
							detail?: string;
						};
						currentData = "";
						if (event.event === "done" && event.result) return event.result;
						if (event.event === "error") {
							throw new Error(event.detail ?? "Correlation job failed.");
						}
					}
				}
			}
		} finally {
			reader.cancel().catch(() => {});
		}

		throw new Error("Correlation stream ended before a terminal payload arrived.");
	}

	async function loadScatter() {
		abortScatter();
		const controller = new AbortController();
		scatterController = controller;
		scatterInflight = true;
		scatterLoading = true;
		scatterError = null;
		universeAttempted = true;

		try {
			const data = await api.get<ScatterResponse>("/research/scatter?limit=80&approved_only=true", undefined, {
				signal: controller.signal,
			});
			scatter = data;
			await loadCorrelation(data.instrument_ids);
			universeLoaded = true;
		} catch (error: unknown) {
			if (error instanceof DOMException && error.name === "AbortError") return;
			scatterError = error instanceof Error ? error.message : "Failed to load research universe.";
			scatter = null;
		} finally {
			if (scatterController === controller) {
				scatterController = null;
				scatterInflight = false;
			}
			scatterLoading = false;
		}
	}

	async function loadCorrelation(instrumentIds: string[]) {
		abortCorrelation();
		const controller = new AbortController();
		correlationController = controller;
		correlationInflight = true;
		correlationLoading = true;
		correlationError = null;
		correlation = null;

		try {
			const token = await getToken();
			const response = await fetch(`${apiBase}/research/correlation/matrix`, {
				method: "POST",
				headers: {
					Authorization: `Bearer ${token}`,
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify({
					instrument_ids: instrumentIds,
					window_days: 252,
				}),
				signal: controller.signal,
			});

			if (response.status === 202) {
				const accepted = (await response.json()) as CorrelationAccepted;
				correlation = await readSseResult(buildStreamUrl(accepted.stream_url), controller.signal);
			} else if (response.ok) {
				correlation = (await response.json()) as CorrelationResponse;
			} else {
				const detail = (await response.json().catch(() => null)) as { detail?: string } | null;
				throw new Error(detail?.detail ?? `Correlation request failed: HTTP ${response.status}`);
			}
		} catch (error: unknown) {
			if (error instanceof DOMException && error.name === "AbortError") return;
			correlationError = error instanceof Error ? error.message : "Failed to load structural correlation.";
		} finally {
			if (correlationController === controller) {
				correlationController = null;
				correlationInflight = false;
			}
			correlationLoading = false;
		}
	}

	$effect(() => {
		activeMode = initialMode;
	});

	$effect(() => {
		const externalId = initialFundId;
		if (!externalId) {
			if (initialMode !== "universe") selectionError = null;
			return;
		}
		if (selectedNode?.id === externalId) return;

		let cancelled = false;
		hydratingSelection = true;
		selectionError = null;

		api
			.get<CatalogDetail>(`/screener/catalog/detail/${encodeURIComponent(externalId)}`)
			.then((detail) => {
				if (cancelled) return;
				selectedNode = {
					id: detail.external_id,
					instrumentId: detail.instrument_id,
					label: detail.name,
					ticker: detail.ticker,
					fundType: detail.fund_type,
					aum: detail.aum,
				};
			})
			.catch((error: unknown) => {
				if (cancelled) return;
				selectionError = error instanceof Error ? error.message : "Failed to load fund context.";
			})
			.finally(() => {
				if (!cancelled) hydratingSelection = false;
			});

		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		if (activeMode !== "universe" || universeLoaded || universeAttempted || scatterLoading || scatterInflight) return;
		void loadScatter();
	});

	onDestroy(() => {
		abortScatter();
		abortCorrelation();
	});
</script>

<div class="tr-shell">
	<div class="tr-header">
		<div class="tr-mode-bar">
			{#each ([
				{ key: "universe", label: "UNIVERSE" },
				{ key: "fund", label: "RETURNS / RISK" },
				{ key: "holdings", label: "HOLDINGS" },
				{ key: "peers", label: "PEERS" },
				{ key: "network", label: "NETWORK" },
			] as const) as mode (mode.key)}
				<button
					type="button"
					class="tr-mode-btn"
					class:tr-mode-btn--active={activeMode === mode.key}
					onclick={() => activeMode = mode.key}
				>
					{mode.label}
				</button>
			{/each}
		</div>
		<div class="tr-context">
			<div class="tr-context-block">
				<span class="tr-context-label">{selectedModeTitle}</span>
				<strong>{cleanLabel(titleLabel)}</strong>
			</div>
			<div class="tr-context-meta">
				<span>{tickerLabel}</span>
				{#if instrumentId}<span>INSTRUMENT READY</span>{/if}
				{#if hydratingSelection}<span>LOADING CONTEXT</span>{/if}
			</div>
		</div>
	</div>

	<div class="tr-root" class:tr-root--network={!showKpiRail}>
		<div class="tr-zone tr-tree" aria-label="Research asset browser">
			<TerminalAssetTree {selectedId} pinnedNode={selectedNode} onSelect={handleSelect} />
		</div>

		<div class="tr-zone tr-main" aria-label="Research workspace">
			<div class="tr-main-header">
				<div class="tr-main-title">
					<span>{activeMode === "universe" ? "Cross-Fund Map" : activeMode === "fund" ? "Returns & Risk Deck" : activeMode === "holdings" ? "Portfolio Composition" : activeMode === "peers" ? "Peer Cohort Intelligence" : "Ownership Network"}</span>
					{#if activeMode !== "universe" && selectedNode}
						<strong>{cleanLabel(selectedNode.label)}</strong>
					{/if}
				</div>
				<div class="tr-main-meta">
					{#if activeMode === "universe"}
						<button
							type="button"
							class="tr-mini-tab"
							class:tr-mini-tab--active={correlationMode === "structural"}
							onclick={() => correlationMode = "structural"}
						>
							STRUCTURAL
						</button>
						<button
							type="button"
							class="tr-mini-tab"
							class:tr-mini-tab--active={correlationMode === "historical"}
							onclick={() => correlationMode = "historical"}
						>
							HISTORICAL
						</button>
					{:else if selectedNode}
						<span class="tr-meta-chip">{cleanLabel(selectedNode.fundType)}</span>
					{/if}
				</div>
			</div>

			{#if selectionError && !selectedNode}
				<div class="tr-empty tr-empty--error">{selectionError}</div>
			{:else if activeMode === "universe"}
				<div class="tr-universe-grid">
					<div class="tr-panel">
						<RiskReturnScatter
							payload={scatter}
							loading={scatterLoading || scatterInflight}
							error={scatterError}
						/>
					</div>
					<div class="tr-panel">
						<CorrelationHeatmap
							payload={correlation}
							mode={correlationMode}
							loading={correlationLoading || correlationInflight}
							error={correlationError}
							onModeChange={(nextMode) => correlationMode = nextMode}
						/>
					</div>
				</div>
			{:else if !selectedNode}
				<div class="tr-empty">
					<div class="tr-empty-title">SELECT A FUND</div>
					<div class="tr-empty-copy">
						Use the asset browser to open diagnostics or holdings intelligence.
					</div>
				</div>
			{:else if activeMode === "fund"}
				<div class="tr-panel tr-panel--fill">
					<TerminalReturnsRiskDeck
						fundId={selectedNode.id}
						ticker={selectedNode.ticker}
						label={selectedNode.label}
					/>
				</div>
			{:else if activeMode === "holdings"}
				<div class="tr-panel tr-panel--fill">
					<TerminalHoldingsGrid
						fundId={selectedNode.id}
						ticker={selectedNode.ticker}
						label={selectedNode.label}
					/>
				</div>
			{:else if activeMode === "peers"}
				<div class="tr-panel tr-panel--fill">
					<TerminalPeerAnalysisPanel
						fundId={selectedNode.id}
						ticker={selectedNode.ticker}
						label={selectedNode.label}
					/>
				</div>
			{:else}
				<div class="tr-panel tr-panel--fill">
					<TerminalHoldingsNetwork
						fundId={selectedNode.id}
						ticker={selectedNode.ticker}
						label={selectedNode.label}
					/>
				</div>
			{/if}
		</div>

		{#if showKpiRail}
			<div class="tr-zone tr-kpis" aria-label="Research inspector">
				<TerminalRiskKpis {selectedNode} />
			</div>
		{/if}
	</div>
</div>

<style>
	.tr-shell {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
	}

	.tr-header {
		display: grid;
		grid-template-columns: auto 1fr;
		align-items: stretch;
		gap: 1px;
		min-height: 40px;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-fg-disabled);
		flex-shrink: 0;
	}

	.tr-mode-bar,
	.tr-context {
		display: flex;
		align-items: center;
		min-width: 0;
		background: var(--terminal-bg-panel);
	}

	.tr-mode-bar {
		padding: 0 12px;
		gap: 14px;
	}

	.tr-mode-btn {
		height: 100%;
		border: none;
		border-bottom: 2px solid transparent;
		background: transparent;
		color: var(--terminal-fg-tertiary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
		cursor: pointer;
		padding: 0 2px;
	}

	.tr-mode-btn:hover {
		color: var(--terminal-fg-secondary);
	}

	.tr-mode-btn--active {
		color: var(--terminal-accent-amber);
		border-bottom-color: var(--terminal-accent-amber);
	}

	.tr-context {
		justify-content: space-between;
		gap: 18px;
		padding: 0 14px;
	}

	.tr-context-block {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
	}

	.tr-context-label,
	.tr-context-meta,
	.tr-main-title span {
		color: var(--terminal-fg-muted);
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.tr-context-block strong,
	.tr-main-title strong {
		overflow: hidden;
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-13);
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tr-context-meta {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		font-variant-numeric: tabular-nums;
	}

	.tr-root {
		display: grid;
		grid-template-areas: "tree main kpis";
		grid-template-columns: 290px 1fr 320px;
		gap: 1px;
		width: 100%;
		height: 100%;
		min-height: 0;
		background: var(--terminal-fg-disabled);
	}

	.tr-root--network {
		grid-template-areas: "tree main";
		grid-template-columns: 290px 1fr;
	}

	.tr-zone {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
	}

	.tr-tree { grid-area: tree; }
	.tr-main {
		grid-area: main;
		display: flex;
		flex-direction: column;
	}
	.tr-kpis { grid-area: kpis; }

	.tr-main-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		min-height: 34px;
		padding: 0 12px;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		flex-shrink: 0;
	}

	.tr-main-title {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
	}

	.tr-main-meta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	.tr-mini-tab,
	.tr-meta-chip {
		height: 20px;
		padding: 0 10px;
		border: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.tr-mini-tab {
		cursor: pointer;
	}

	.tr-mini-tab--active {
		border-color: var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
	}

	.tr-universe-grid {
		display: grid;
		grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
		gap: 1px;
		flex: 1;
		min-height: 0;
		background: var(--terminal-fg-disabled);
	}

	.tr-panel {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
	}

	.tr-panel--fill {
		flex: 1;
		min-height: 0;
	}

	.tr-empty {
		display: flex;
		flex: 1;
		min-height: 0;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 32px;
		text-align: center;
	}

	.tr-empty-title {
		color: var(--terminal-fg-secondary);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.14em;
	}

	.tr-empty-copy,
	.tr-empty--error {
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
		line-height: 1.5;
		max-width: 360px;
	}

	.tr-empty--error {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--terminal-status-error);
		padding: 24px;
	}

	@media (max-width: 1280px) {
		.tr-root {
			grid-template-columns: 260px 1fr 300px;
		}

		.tr-root--network {
			grid-template-columns: 250px 1fr;
		}
	}
</style>
