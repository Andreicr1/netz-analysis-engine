<!--
  DriftHistoryPanel — lazy-loaded drift event workbench.
  Fetches GET /analytics/strategy-drift/{instrument_id}/history.
  Renders a scatter chart (drift_magnitude × detected_at) + DataTable with row expansion.
  Supports severity filter, date range filter, and client-side CSV export.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { renderComponent } from "@tanstack/svelte-table";
	import {
		DataTable,
		EmptyState,
		StatusBadge,
		formatDateTime,
		formatNumber,
	} from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import { createClientApiClient } from "$lib/api/client";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import { getContext } from "svelte";

	// Inline types from API schema (DriftEventOut / DriftHistoryOut)
	type DriftEvent = {
		id: string;
		instrument_id: string;
		status: string;
		severity: string;
		anomalous_count: number;
		total_metrics: number;
		metric_details?: Record<string, unknown>[] | null;
		is_current: boolean;
		detected_at: string;
		created_at?: string | null;
		snapshot_date?: string | null;
		drift_magnitude?: string | null;
		drift_threshold?: string | null;
		rebalance_triggered?: boolean | null;
		breached: boolean;
		asset_class_breakdown?: Record<string, unknown>[] | null;
	};

	type DriftHistory = {
		instrument_id: string;
		instrument_name: string;
		events: DriftEvent[];
		total: number;
		computed_at?: string | null;
	};

	interface Props {
		instrumentId: string;
		instrumentName?: string;
	}

	let { instrumentId, instrumentName = "Instrument" }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Data ───────────────────────────────────────────────────
	let events = $state.raw<DriftEvent[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let computedAt = $state<string | null>(null);

	// ── Filters ────────────────────────────────────────────────
	let filterSeverity = $state<string>("");
	let filterFrom = $state<string>("");
	let filterTo = $state<string>("");

	// ── Derived: filtered events ────────────────────────────────
	let filteredEvents = $derived.by(() => {
		let result = events;
		if (filterSeverity) {
			result = result.filter((e) => e.severity === filterSeverity);
		}
		if (filterFrom) {
			const from = new Date(filterFrom).getTime();
			result = result.filter((e) => new Date(e.detected_at).getTime() >= from);
		}
		if (filterTo) {
			const to = new Date(filterTo).getTime();
			result = result.filter((e) => new Date(e.detected_at).getTime() <= to);
		}
		return result;
	});

	// ── Unique severities for filter select ────────────────────
	let severities = $derived(
		[...new Set(events.map((e) => e.severity))].filter(Boolean).sort(),
	);

	// ── Table columns ───────────────────────────────────────────
	const columns = [
		{
			id: "detected_at",
			accessorKey: "detected_at",
			header: "Detected At",
			cell: (info: { getValue: () => unknown }) => formatDateTime(info.getValue() as string),
		},
		{
			id: "severity",
			accessorKey: "severity",
			header: "Severity",
			cell: (info: { getValue: () => unknown }) => {
				const val = (info.getValue() as string) ?? "";
				return renderComponent(StatusBadge, { status: val, resolve: resolveWealthStatus });
			},
		},
		{
			id: "status",
			accessorKey: "status",
			header: "Status",
		},
		{
			id: "anomalous_count",
			accessorKey: "anomalous_count",
			header: "Anomalous",
			cell: (info: { getValue: () => unknown }) => String(info.getValue() ?? "—"),
		},
		{
			id: "drift_magnitude",
			accessorKey: "drift_magnitude",
			header: "Drift Magnitude",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue();
				if (v == null) return "—";
				const num = typeof v === "string" ? parseFloat(v) : (v as number);
				return isNaN(num) ? "—" : formatNumber(num, 4);
			},
		},
		{
			id: "drift_threshold",
			accessorKey: "drift_threshold",
			header: "Threshold",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue();
				if (v == null) return "—";
				const num = typeof v === "string" ? parseFloat(v) : (v as number);
				return isNaN(num) ? "—" : formatNumber(num, 4);
			},
		},
		{
			id: "rebalance_triggered",
			accessorKey: "rebalance_triggered",
			header: "Rebalance",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue();
				return v === true ? "Yes" : v === false ? "No" : "—";
			},
		},
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	] as any[];

	// ── Scatter chart option ────────────────────────────────────
	let scatterOption = $derived.by(() => {
		const pts = filteredEvents
			.filter((e) => e.drift_magnitude != null)
			.map((e) => {
				const mag = typeof e.drift_magnitude === "string"
					? parseFloat(e.drift_magnitude)
					: (e.drift_magnitude as number | null | undefined);
				return [new Date(e.detected_at).getTime(), mag ?? 0, e.severity] as [number, number, string];
			});

		if (pts.length === 0) return null;

		return {
			tooltip: {
				trigger: "item",
				formatter: (params: { value: [number, number, string] }) =>
					`${formatDateTime(new Date(params.value[0]).toISOString())}<br/>Magnitude: ${formatNumber(params.value[1], 4)}<br/>Severity: ${params.value[2]}`,
			},
			grid: { left: 70, right: 20, top: 20, bottom: 50, containLabel: true },
			xAxis: {
				type: "time",
				axisLabel: {
					formatter: (v: number) => {
						const d = new Date(v);
						return `${d.getDate().toString().padStart(2, "0")}/${(d.getMonth() + 1).toString().padStart(2, "0")}`;
					},
				},
			},
			yAxis: {
				type: "value",
				name: "Magnitude",
				nameLocation: "middle" as const,
				nameGap: 50,
			},
			dataZoom: [
				{ type: "inside", xAxisIndex: 0 },
				{ type: "slider", xAxisIndex: 0, bottom: 5, height: 20 },
			],
			series: [
				{
					type: "scatter",
					large: true,
					largeThreshold: 500,
					data: pts.map(([x, y]) => [x, y]),
					symbolSize: 8,
					itemStyle: { opacity: 0.75 },
				},
			],
		} as Record<string, unknown>;
	});

	// ── Fetch ───────────────────────────────────────────────────
	async function fetchHistory() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const params = new URLSearchParams();
			if (filterFrom) params.set("from_date", filterFrom);
			if (filterTo) params.set("to_date", filterTo);
			if (filterSeverity) params.set("severity", filterSeverity);
			params.set("limit", "500");
			const qs = params.toString() ? `?${params.toString()}` : "";
			const res = await api.get<DriftHistory>(
				`/analytics/strategy-drift/${instrumentId}/history${qs}`,
			);
			events = Array.isArray(res.events) ? res.events : [];
			computedAt = res.computed_at ?? null;
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load drift history";
			events = [];
		} finally {
			loading = false;
		}
	}

	// ── CSV export ──────────────────────────────────────────────
	function exportCSV() {
		const header = ["detected_at", "severity", "status", "anomalous_count", "drift_magnitude", "drift_threshold", "rebalance_triggered"].join(",");
		const rows = filteredEvents.map((e) =>
			[
				e.detected_at,
				e.severity,
				e.status,
				e.anomalous_count,
				e.drift_magnitude ?? "",
				e.drift_threshold ?? "",
				e.rebalance_triggered ?? "",
			]
				.map((v) => `"${String(v).replace(/"/g, '""')}"`)
				.join(","),
		);
		const csv = [header, ...rows].join("\n");
		const blob = new Blob([csv], { type: "text/csv" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `drift-history-${instrumentId}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}

	// Load on mount
	let mounted = $state(false);
	onMount(() => {
		mounted = true;
		fetchHistory();
	});
</script>

{#if mounted}
	<div class="space-y-4">
		<!-- Header row with filters + export -->
		<div class="flex flex-wrap items-end gap-3">
			<!-- Severity filter -->
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-(--netz-text-secondary)" for="drift-severity-filter">
					Severity
				</label>
				<select
					id="drift-severity-filter"
					class="h-8 rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 text-xs text-(--netz-text-primary)"
					bind:value={filterSeverity}
				>
					<option value="">All</option>
					{#each severities as sev (sev)}
						<option value={sev}>{sev}</option>
					{/each}
				</select>
			</div>

			<!-- Date from -->
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-(--netz-text-secondary)" for="drift-from-filter">
					From
				</label>
				<input
					id="drift-from-filter"
					type="date"
					class="h-8 rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 text-xs text-(--netz-text-primary)"
					bind:value={filterFrom}
				/>
			</div>

			<!-- Date to -->
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-(--netz-text-secondary)" for="drift-to-filter">
					To
				</label>
				<input
					id="drift-to-filter"
					type="date"
					class="h-8 rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 text-xs text-(--netz-text-primary)"
					bind:value={filterTo}
				/>
			</div>

			<button
				class="ml-auto inline-flex h-8 items-center gap-1.5 rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 text-xs font-medium text-(--netz-text-primary) hover:bg-(--netz-surface-alt) disabled:opacity-40"
				onclick={exportCSV}
				disabled={filteredEvents.length === 0}
			>
				Export CSV
			</button>
		</div>

		{#if computedAt}
			<p class="text-xs text-(--netz-text-muted)">
				Computed: {formatDateTime(computedAt)}
			</p>
		{/if}

		{#if loading}
			<div class="flex h-24 items-center justify-center">
				<span class="text-sm text-(--netz-text-muted)">Loading drift history…</span>
			</div>
		{:else if error}
			<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{error}
			</div>
		{:else if filteredEvents.length === 0}
			<EmptyState
				title="No drift events"
				message="No drift events found for the selected filters."
			/>
		{:else}
			<!-- Scatter chart -->
			{#if scatterOption}
				<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-4">
					<h3 class="mb-3 text-sm font-semibold text-(--netz-text-primary)">
						Drift Magnitude Timeline — {instrumentName}
					</h3>
					<ChartContainer
						option={scatterOption}
						height={260}
						ariaLabel="Drift magnitude scatter chart"
					/>
				</div>
			{/if}

			<!-- Event table with row expansion for metric_details -->
			<DataTable
				data={filteredEvents as unknown as Record<string, unknown>[]}
				{columns}
				pageSize={20}
			>
				{#snippet expandedRow(row)}
					{@const typedRow = row as unknown as DriftEvent}
					<div class="space-y-2 p-2">
						{#if typedRow.metric_details && typedRow.metric_details.length > 0}
							<h4 class="text-xs font-semibold uppercase tracking-wider text-(--netz-text-secondary)">
								Metric Details
							</h4>
							<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
								{#each typedRow.metric_details as detail, i (i)}
									<div class="rounded border border-(--netz-border) bg-(--netz-surface) p-2 text-xs">
										{#each Object.entries(detail ?? {}) as [key, val] (key)}
											<div class="flex justify-between gap-2">
												<span class="text-(--netz-text-muted)">{key}</span>
												<span class="font-medium text-(--netz-text-primary)">
													{String(val ?? "—")}
												</span>
											</div>
										{/each}
									</div>
								{/each}
							</div>
						{:else}
							<p class="text-xs text-(--netz-text-muted)">No metric details available.</p>
						{/if}
						{#if typedRow.breached}
							<div class="inline-flex items-center gap-1 rounded-full bg-(--netz-status-error)/15 px-2 py-0.5 text-xs font-medium text-(--netz-status-error)">
								Threshold Breached
							</div>
						{/if}
					</div>
				{/snippet}
			</DataTable>
		{/if}
	</div>
{/if}
