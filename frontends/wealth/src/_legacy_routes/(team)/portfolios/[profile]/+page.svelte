<!--
  Portfolio Profile Workbench — Section 3.Wealth.6 of the UX Remediation Plan.

  Multi-region allocation navigator, DataTable with multi-sort + row expansion,
  drift history export, rebalancing tab with IC governance workflow.
  computed_at from server only — never Date.now().
-->
<script lang="ts">
	import {
		PageHeader,
		MetricCard,
		SectionCard,
		EmptyState,
		StatusBadge,
		Card,
		Button,
		ContextPanel,
		ActionButton,
		DataTable,
		PageTabs,
		formatDate,
		formatDateTime,
		formatPercent,
		formatNumber,
	} from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import StaleBanner from "$lib/components/StaleBanner.svelte";
	import {
		globalChartOptions,
		statusColors,
	} from "@netz/ui/charts/echarts-setup";
	import type { ColumnDef } from "@tanstack/svelte-table";
	import DriftHistoryPanel from "$lib/components/DriftHistoryPanel.svelte";
	import RebalancingTab from "./RebalancingTab.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const riskStore = getContext<RiskStore>("netz:riskStore");

	let { data }: { data: PageData } = $props();

	// ── API types matching api.d.ts schemas — no invented shapes ─────────────
	type PortfolioSnapshotRead = {
		snapshot_id: string;
		profile: string;
		snapshot_date: string;
		weights: Record<string, unknown>;
		fund_selection?: Record<string, unknown> | null;
		cvar_current?: string | null;
		cvar_limit?: string | null;
		cvar_utilized_pct?: string | null;
		trigger_status?: string | null;
		consecutive_breach_days: number;
		regime?: string | null;
		core_weight?: string | null;
		satellite_weight?: string | null;
		regime_probs?: Record<string, unknown> | null;
		cvar_lower_5?: string | null;
		cvar_upper_95?: string | null;
		computed_at?: string | null;
	};

	type PortfolioSummary = {
		profile: string;
		snapshot_date?: string | null;
		cvar_current?: string | null;
		cvar_limit?: string | null;
		cvar_utilized_pct?: string | null;
		trigger_status?: string | null;
		regime?: string | null;
		core_weight?: string | null;
		satellite_weight?: string | null;
		computed_at?: string | null;
	};

	// ── Server data ───────────────────────────────────────────────────────────
	let profile = $derived(data.profile as string);
	let snapshot = $derived(data.snapshot as PortfolioSnapshotRead | null);
	let summary = $derived(data.portfolio as PortfolioSummary | null);

	// CVaR from risk store (SSE-primary, poll-fallback)
	let cvarStatus = $derived(riskStore?.cvarByProfile?.[profile] ?? null);
	let cvarHistory = $derived(riskStore?.cvarHistoryByProfile?.[profile] ?? []);

	// Freshness from server computed_at ONLY — never Date.now()
	let computedAt = $derived(
		cvarStatus?.computed_at
			?? snapshot?.computed_at
			?? summary?.computed_at
			?? null
	);

	// ── Region allocation navigator ──────────────────────────────────────────

	const REGIONS = ["global", "latam", "us", "europe", "asia"] as const;
	type Region = typeof REGIONS[number];

	let selectedRegion = $state<Region | "all">("all");

	// Weights from snapshot — typed as record
	let weights: Record<string, number> = $derived.by(() => {
		const raw = snapshot?.weights ?? {};
		const out: Record<string, number> = {};
		for (const [k, v] of Object.entries(raw)) {
			if (typeof v === "number") out[k] = v;
		}
		return out;
	});

	// Allocation rows — split by region tag if available (fund_name prefix heuristic)
	function inferRegion(name: string): Region {
		const lower = name.toLowerCase();
		if (lower.includes("latam") || lower.includes("br") || lower.includes("brasil")) return "latam";
		if (lower.includes("us") || lower.includes("eua") || lower.includes("american")) return "us";
		if (lower.includes("europe") || lower.includes("eu") || lower.includes("eur")) return "europe";
		if (lower.includes("asia") || lower.includes("japan") || lower.includes("china")) return "asia";
		return "global";
	}

	type AllocationRow = {
		fund_name: string;
		region: Region;
		current_weight: number;
		target_weight: number | null;
		delta_weight: number | null;
	};

	let allRows = $derived.by((): AllocationRow[] => {
		const fundSelection = snapshot?.fund_selection ?? {};
		return Object.entries(weights).map(([name, current]) => {
			const sel = typeof fundSelection[name] === "object" && fundSelection[name] !== null
				? fundSelection[name] as Record<string, unknown>
				: null;
			const target = typeof sel?.target_weight === "number" ? sel.target_weight : null;
			return {
				fund_name: name,
				region: inferRegion(name),
				current_weight: current,
				target_weight: target,
				delta_weight: target !== null ? current - target : null,
			};
		}).sort((a, b) => b.current_weight - a.current_weight);
	});

	let filteredRows = $derived(
		selectedRegion === "all"
			? allRows
			: allRows.filter((r) => r.region === selectedRegion)
	);

	// Region totals for navigator
	let regionTotals = $derived.by(() => {
		const totals: Record<string, number> = {};
		for (const r of allRows) {
			totals[r.region] = (totals[r.region] ?? 0) + r.current_weight;
		}
		return totals;
	});

	// ── DataTable columns with multi-sort ────────────────────────────────────

	type AllocationRecord = Record<string, unknown>;

	const allocationColumns: ColumnDef<AllocationRecord>[] = [
		{
			accessorKey: "fund_name",
			header: "Fund",
			enableSorting: true,
			cell: (info) => String(info.getValue() ?? "--"),
		},
		{
			accessorKey: "region",
			header: "Region",
			enableSorting: true,
			cell: (info) => String(info.getValue() ?? "--"),
		},
		{
			accessorKey: "current_weight",
			header: "Current Weight",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "number" ? formatPercent(v, 2, "en-US") : "--";
			},
		},
		{
			accessorKey: "target_weight",
			header: "Target Weight",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "number" ? formatPercent(v, 2, "en-US") : "--";
			},
		},
		{
			accessorKey: "delta_weight",
			header: "Delta Weight",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				if (typeof v !== "number") return "--";
				const pct = v * 100;
				const sign = pct >= 0 ? "+" : "";
				return `${sign}${formatNumber(pct, 2, "en-US")}pp`;
			},
		},
	];

	let tableRows = $derived<AllocationRecord[]>(
		filteredRows.map((r): AllocationRecord => ({
			fund_name: r.fund_name,
			region: r.region,
			current_weight: r.current_weight,
			target_weight: r.target_weight,
			delta_weight: r.delta_weight,
		}))
	);

	// ── CVaR timeline chart ───────────────────────────────────────────────────

	let cvarChartOption = $derived.by(() => {
		if (!cvarHistory || cvarHistory.length === 0) return null;

		const limitRaw = cvarStatus?.cvar_limit ?? snapshot?.cvar_limit;
		const limit = typeof limitRaw === "string" ? parseFloat(limitRaw) : (limitRaw ?? -0.08);
		const warningThreshold = limit * 0.8;

		return {
			...globalChartOptions,
			grid: { containLabel: true, left: 60, right: 20, top: 20, bottom: 50 },
			xAxis: { type: "time" },
			yAxis: {
				type: "value",
				inverse: true,
				axisLabel: { formatter: (v: number) => formatPercent(v, 1, "en-US") },
			},
			series: [
				{
					name: "CVaR 95%",
					type: "line",
					data: cvarHistory.map((p) => [p.date, p.cvar]),
					smooth: true,
					lineStyle: { width: 2 },
					showSymbol: false,
					markLine: {
						silent: true,
						symbol: "none",
						data: [
							{
								yAxis: limit,
								label: { formatter: `Limit: ${formatPercent(limit, 1, "en-US")}`, position: "end" },
								lineStyle: { color: statusColors.breach, type: "dashed", width: 2 },
							},
							{
								yAxis: warningThreshold,
								label: { formatter: "Warning (80%)", position: "end" },
								lineStyle: { color: statusColors.warning, type: "dashed", width: 1 },
							},
						],
					},
					markArea: {
						silent: true,
						data: [
							[
								{ yAxis: warningThreshold, itemStyle: { color: "rgba(245,158,11,0.06)" } },
								{ yAxis: limit },
							],
							[
								{ yAxis: limit, itemStyle: { color: "rgba(239,68,68,0.08)" } },
								{ yAxis: limit * 1.5 },
							],
						],
					},
				},
			],
		};
	});

	// ── Drift history panel ───────────────────────────────────────────────────

	let showDriftHistory = $state(false);
	let exportingDrift = $state(false);

	type PortfolioRecord = { id: string; display_name?: string | null };
	let portfolioRecord = $derived(data.portfolio as PortfolioRecord | null);
	let driftInstrumentId = $derived(portfolioRecord?.id ?? profile);
	let driftInstrumentName = $derived(portfolioRecord?.display_name ?? profile);

	async function exportDriftHistory() {
		exportingDrift = true;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/analytics/strategy-drift/${driftInstrumentId}/export?format=csv`);
			const a = document.createElement("a");
			a.href = URL.createObjectURL(blob);
			a.download = `drift-history-${profile}.csv`;
			a.click();
			URL.revokeObjectURL(a.href);
		} catch (e) {
			// silent error for export
		} finally {
			exportingDrift = false;
		}
	}

	// Profile display name
	let profileLabel = $derived(
		profile.charAt(0).toUpperCase() + profile.slice(1)
	);

	function fmtPct(v: string | number | null | undefined): string {
		const n = typeof v === "string" ? parseFloat(v) : v;
		return formatPercent(n, 1, "en-US");
	}

	// CVaR numeric values for rebalancing tab
	let cvarCurrentNum = $derived.by((): number | null => {
		const raw = cvarStatus?.cvar_current ?? snapshot?.cvar_current;
		if (typeof raw === "number") return raw;
		if (typeof raw === "string") return parseFloat(raw);
		return null;
	});
	let cvarLimitNum = $derived.by((): number | null => {
		const raw = cvarStatus?.cvar_limit ?? snapshot?.cvar_limit;
		if (typeof raw === "number") return raw;
		if (typeof raw === "string") return parseFloat(raw);
		return null;
	});

	// ── Tab config ──
	const portfolioTabs = [
		{ value: "overview", label: "Overview" },
		{ value: "rebalancing", label: "Rebalancing" },
	];
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">

	<!-- Stale banner — server computed_at only -->
	{#if riskStore?.status === "stale"}
		<StaleBanner lastUpdated={riskStore.computedAt ? new Date(riskStore.computedAt) : null} onRefresh={() => riskStore.refresh()} />
	{/if}

	<!-- Page header -->
	<PageHeader title="{profileLabel} Portfolio Workbench">
		{#snippet actions()}
			<div class="flex flex-wrap gap-2">
				<Button
					variant="outline"
					size="sm"
					onclick={exportDriftHistory}
					disabled={exportingDrift}
				>
					{exportingDrift ? "Exporting..." : "Export Drift History"}
				</Button>
				<Button variant="outline" size="sm" onclick={() => showDriftHistory = true}>
					View Drift History
				</Button>
			</div>
		{/snippet}
	</PageHeader>

	<!-- ════════════════════════════════════════════════════════════════════════
	     KPI row — freshness from server computed_at ONLY
	     ════════════════════════════════════════════════════════════════════════ -->
	<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
		<MetricCard
			label="CVaR 95%"
			value={fmtPct(cvarStatus?.cvar_current ?? snapshot?.cvar_current)}
			sublabel="Limit: {fmtPct(cvarStatus?.cvar_limit ?? snapshot?.cvar_limit)} | Util: {fmtPct(cvarStatus?.cvar_utilized_pct ?? snapshot?.cvar_utilized_pct)}"
			status={
				parseFloat(String(cvarStatus?.cvar_utilized_pct ?? 0)) > 1 ? "breach" :
				parseFloat(String(cvarStatus?.cvar_utilized_pct ?? 0)) > 0.8 ? "warn" : undefined
			}
		/>
		<MetricCard
			label="Core / Satellite"
			value="{fmtPct(snapshot?.core_weight)} / {fmtPct(snapshot?.satellite_weight)}"
			sublabel="Regime: {cvarStatus?.regime ?? snapshot?.regime ?? '--'}"
		/>
		<MetricCard
			label="CVaR Breach Days"
			value={String(cvarStatus?.consecutive_breach_days ?? 0)}
			sublabel={cvarStatus?.trigger_status ?? snapshot?.trigger_status ?? "--"}
			status={
				(cvarStatus?.consecutive_breach_days ?? 0) > 3 ? "breach" :
				(cvarStatus?.consecutive_breach_days ?? 0) > 0 ? "warn" : undefined
			}
		/>
		<MetricCard
			label="Snapshot"
			value={snapshot?.snapshot_date ? formatDate(snapshot.snapshot_date) : "--"}
			sublabel={computedAt
				? `Calculado: ${formatDateTime(computedAt)}`
				: "Awaiting pipeline"}
		/>
	</div>

	<!-- ════════════════════════════════════════════════════════════════════════
	     Tabbed content: Overview | Rebalancing
	     ════════════════════════════════════════════════════════════════════════ -->
	<PageTabs tabs={portfolioTabs} defaultTab="overview">
		{#snippet children(activeTab)}
			{#if activeTab === "overview"}
				<!-- CVaR Timeline -->
				<SectionCard title="CVaR Timeline" subtitle="Rolling 12M with limit and regime bands">
					{#if cvarChartOption}
						<ChartContainer option={cvarChartOption} height={360} ariaLabel="{profile} CVaR timeline" />
					{:else}
						<EmptyState
							title="No CVaR history"
							message="The chart will appear after the daily risk pipeline runs."
						/>
					{/if}
					{#if cvarStatus && computedAt}
						<p class="mt-2 text-right text-xs text-(--netz-text-muted)">
							Computed at: <time datetime={computedAt}>{formatDateTime(computedAt)}</time>
						</p>
					{/if}
				</SectionCard>

				<!-- Multi-region allocation navigator -->
				<SectionCard title="Allocation by Region" subtitle="Multi-region allocation navigator">
					<div class="mb-4 flex flex-wrap gap-2">
						<button
							class="rounded-full px-3 py-1 text-sm font-medium transition-colors"
							class:bg-(--netz-brand-primary)={selectedRegion === "all"}
							class:text-white={selectedRegion === "all"}
							class:bg-(--netz-surface-inset)={selectedRegion !== "all"}
							class:text-(--netz-text-secondary)={selectedRegion !== "all"}
							onclick={() => selectedRegion = "all"}
						>
							All
						</button>
						{#each REGIONS as region (region)}
							<button
								class="rounded-full px-3 py-1 text-sm font-medium transition-colors"
								class:bg-(--netz-brand-primary)={selectedRegion === region}
								class:text-white={selectedRegion === region}
								class:bg-(--netz-surface-inset)={selectedRegion !== region}
								class:text-(--netz-text-secondary)={selectedRegion !== region}
								onclick={() => selectedRegion = region}
							>
								{region.toUpperCase()}
								{#if regionTotals[region]}
									<span class="ml-1 text-xs opacity-70">({formatPercent(regionTotals[region], 1, "en-US")})</span>
								{/if}
							</button>
						{/each}
					</div>

					{#if tableRows.length > 0}
						<DataTable
							data={tableRows}
							columns={allocationColumns}
							pageSize={20}
							filterColumn="fund_name"
							filterPlaceholder="Search fund..."
						>
							{#snippet expandedRow(row)}
								<div class="px-4 py-3 text-sm text-(--netz-text-secondary) space-y-1">
									<p><span class="font-medium">Fund:</span> {String(row.fund_name ?? "--")}</p>
									<p><span class="font-medium">Region:</span> {String(row.region ?? "--")}</p>
									<p><span class="font-medium">Current Weight:</span> {typeof row.current_weight === "number" ? formatPercent(row.current_weight, 4, "en-US") : "--"}</p>
									{#if row.target_weight !== null}
										<p><span class="font-medium">Target Weight:</span> {typeof row.target_weight === "number" ? formatPercent(row.target_weight, 4, "en-US") : "--"}</p>
									{/if}
									{#if row.delta_weight !== null}
										<p>
											<span class="font-medium">Deviation:</span>
											{#if typeof row.delta_weight === "number"}
												<span class={row.delta_weight > 0 ? "text-(--netz-success)" : "text-(--netz-danger)"}>
													{row.delta_weight > 0 ? "+" : ""}{formatNumber(row.delta_weight * 100, 2, "en-US")}pp
												</span>
											{/if}
										</p>
									{/if}
								</div>
							{/snippet}
						</DataTable>
					{:else}
						<EmptyState
							title="No allocation data"
							message="Allocation data will appear after the latest snapshot is available."
						/>
					{/if}
				</SectionCard>

			{:else if activeTab === "rebalancing"}
				<RebalancingTab
					{profile}
					currentWeights={weights}
					cvarCurrent={cvarCurrentNum}
					cvarLimit={cvarLimitNum}
				/>
			{/if}
		{/snippet}
	</PageTabs>
</div>

<!-- Drift history side panel -->
{#if showDriftHistory}
	<ContextPanel
		open={showDriftHistory}
		title="Drift History -- {profileLabel}"
		onClose={() => showDriftHistory = false}
		width="720px"
	>
		<div class="p-4">
			<DriftHistoryPanel
				instrumentId={driftInstrumentId}
				instrumentName={driftInstrumentName}
			/>
		</div>
	</ContextPanel>
{/if}
