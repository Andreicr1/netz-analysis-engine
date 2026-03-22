<!--
  FundsView — Fund Universe with status tabs + detail panel.
  Self-loading component for embedding in Screener tabs.
-->
<script lang="ts">
	import { Badge, Button, EmptyState, Skeleton, formatAUM as formatSharedAUM, formatDate as formatSharedDate, formatNumber } from "@netz/ui";
	import FundDetailPanel from "$lib/components/FundDetailPanel.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	type FundRow = {
		id: string;
		name: string;
		subcategory: string | null;
		manager: string | null;
		aum: number | null;
		strategy: string | null;
		status: string | null;
		dd_report_status: string | null;
		dd_report_id: string | null;
		score: number | null;
		updated_at: string | null;
		isin?: string | null;
		cnpj?: string | null;
		inception_date?: string | null;
		annual_return?: number | null;
		sharpe_ratio?: number | null;
		max_drawdown?: number | null;
		cvar_95?: number | null;
	};

	let funds = $state<FundRow[]>([]);
	let loading = $state(true);

	async function fetchData() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.get("/funds");
			funds = (result ?? []) as FundRow[];
		} catch {
			funds = [];
		} finally {
			loading = false;
		}
	}

	// Status tabs
	type StatusTab = "todos" | "aprovados" | "dd_pendente" | "watchlist";
	let activeStatusTab = $state<StatusTab>("todos");

	const statusTabs: { value: StatusTab; label: string }[] = [
		{ value: "todos", label: "All" },
		{ value: "aprovados", label: "Approved" },
		{ value: "dd_pendente", label: "DD Pending" },
		{ value: "watchlist", label: "Watchlist" },
	];

	let tabCounts = $derived({
		todos: funds.length,
		aprovados: funds.filter((f) => f.status === "aprovado").length,
		dd_pendente: funds.filter((f) => f.dd_report_status === "pendente" || f.status === "dd_pendente").length,
		watchlist: funds.filter((f) => f.status === "watchlist").length,
	});

	let filteredFunds = $derived.by((): FundRow[] => {
		switch (activeStatusTab) {
			case "aprovados": return funds.filter((f) => f.status === "aprovado");
			case "dd_pendente": return funds.filter((f) => f.dd_report_status === "pendente" || f.status === "dd_pendente");
			case "watchlist": return funds.filter((f) => f.status === "watchlist");
			default: return funds;
		}
	});

	// Side panel
	let selectedFund = $state<FundRow | null>(null);
	let panelOpen = $state(false);
	let closingTimeout: ReturnType<typeof setTimeout> | null = null;

	function openPanel(fund: FundRow) {
		if (closingTimeout) { clearTimeout(closingTimeout); closingTimeout = null; }
		selectedFund = fund;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		closingTimeout = setTimeout(() => { selectedFund = null; closingTimeout = null; }, 220);
	}

	$effect(() => {
		return () => { if (closingTimeout) { clearTimeout(closingTimeout); closingTimeout = null; } };
	});

	// Strategy badge colors
	const strategyColors: Record<string, { bg: string; text: string }> = {
		"Senior Secured": { bg: "color-mix(in srgb, var(--netz-teal, #14b8a6) 15%, transparent)", text: "var(--netz-teal, #14b8a6)" },
		"Long Only": { bg: "color-mix(in srgb, var(--netz-brand-primary) 15%, transparent)", text: "var(--netz-brand-primary)" },
		"Fixed Income": { bg: "color-mix(in srgb, #8b5cf6 15%, transparent)", text: "#8b5cf6" },
		"Risk Parity": { bg: "color-mix(in srgb, var(--netz-warning) 15%, transparent)", text: "var(--netz-warning)" },
		"EM Bonds": { bg: "color-mix(in srgb, var(--netz-success) 15%, transparent)", text: "var(--netz-success)" },
	};

	function getStrategyStyle(strategy: string | null): string {
		if (!strategy) return "";
		const colors = strategyColors[strategy];
		if (!colors) return `background: color-mix(in srgb, var(--netz-text-muted) 15%, transparent); color: var(--netz-text-muted);`;
		return `background: ${colors.bg}; color: ${colors.text};`;
	}

	function getStatusStyle(status: string | null): string {
		switch (status) {
			case "aprovado": return "background: color-mix(in srgb, var(--netz-success) 15%, transparent); color: var(--netz-success);";
			case "watchlist": return "background: color-mix(in srgb, var(--netz-warning) 15%, transparent); color: var(--netz-warning);";
			default: return "background: color-mix(in srgb, var(--netz-text-muted) 15%, transparent); color: var(--netz-text-muted);";
		}
	}

	function getStatusLabel(status: string | null): string {
		switch (status) {
			case "aprovado": return "Approved";
			case "watchlist": return "Watchlist";
			case "dd_pendente": return "DD Pending";
			default: return status ?? "—";
		}
	}

	function getDDReportStyle(ddStatus: string | null): string {
		switch (ddStatus) {
			case "complete": return "background: color-mix(in srgb, var(--netz-success) 15%, transparent); color: var(--netz-success);";
			case "generating": return "background: color-mix(in srgb, var(--netz-brand-primary) 15%, transparent); color: var(--netz-brand-primary);";
			default: return "background: color-mix(in srgb, var(--netz-text-muted) 15%, transparent); color: var(--netz-text-muted);";
		}
	}

	function getDDReportLabel(ddStatus: string | null): string {
		switch (ddStatus) {
			case "complete": return "Complete";
			case "generating": return "Generating...";
			case "pendente": return "Pending";
			default: return "Pending";
		}
	}

	function formatAum(value: number | null): string { return formatSharedAUM(value, "BRL", "pt-BR"); }
	function formatDate(value: string | null): string { return formatSharedDate(value); }

	// Load on mount
	fetchData();
</script>

<div class="space-y-4">
	{#if loading}
		<div class="space-y-3">
			{#each Array.from({length: 5}, (_, i) => i) as i (i)}
				<Skeleton class="h-14 rounded-lg" />
			{/each}
		</div>
	{:else}
		<div class="flex items-center justify-between">
			<h3 class="text-sm font-semibold text-(--netz-text-primary)">Fund Universe ({funds.length})</h3>
			<Button class="gap-1.5">
				<svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
					<path d="M10 4v12M4 10h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
				</svg>
				Add Fund
			</Button>
		</div>

		<div class="overflow-hidden rounded-(--netz-radius-xl) border border-(--netz-border-subtle) bg-(--netz-surface-panel) shadow-(--netz-shadow-card)">
			<!-- Status Tabs -->
			<div class="border-b border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-3">
				<div class="flex flex-wrap items-center gap-2">
					{#each statusTabs as tab (tab.value)}
						<button
							class="inline-flex min-h-(--netz-space-control-height-md) items-center gap-2 rounded-(--netz-radius-md) border px-3.5 py-2 text-sm font-medium tracking-[-0.01em] transition-[color,background-color,border-color,box-shadow] duration-(--netz-duration-fast)"
							class:border-(--netz-border)={activeStatusTab === tab.value}
							class:bg-(--netz-surface-elevated)={activeStatusTab === tab.value}
							class:text-(--netz-text-primary)={activeStatusTab === tab.value}
							class:shadow-(--netz-shadow-1)={activeStatusTab === tab.value}
							class:border-transparent={activeStatusTab !== tab.value}
							class:bg-transparent={activeStatusTab !== tab.value}
							class:text-(--netz-text-muted)={activeStatusTab !== tab.value}
							class:hover:bg-(--netz-accent-soft)={activeStatusTab !== tab.value}
							class:hover:text-(--netz-text-secondary)={activeStatusTab !== tab.value}
							onclick={() => (activeStatusTab = tab.value)}
						>
							{tab.label}
							{#if tabCounts[tab.value] > 0}
								<Badge variant={activeStatusTab === tab.value ? "default" : "secondary"}>
									{tabCounts[tab.value]}
								</Badge>
							{/if}
						</button>
					{/each}
				</div>
			</div>

			{#if filteredFunds.length > 0}
				<div class="overflow-x-auto">
					<table class="w-full min-w-200 text-sm">
						<thead>
							<tr class="border-b border-(--netz-border-subtle) bg-(--netz-surface-highlight)">
								<th class="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">Fund</th>
								<th class="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">Manager</th>
								<th class="px-4 py-3.5 text-right text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">AUM</th>
								<th class="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">Strategy</th>
								<th class="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">Status</th>
								<th class="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">DD Report</th>
								<th class="px-4 py-3.5 text-right text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">Score</th>
								<th class="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">Updated</th>
							</tr>
						</thead>
						<tbody>
							{#each filteredFunds as fund (fund.id)}
								<tr
									class="cursor-pointer border-b border-(--netz-border-subtle) bg-(--netz-surface-elevated) transition-colors last:border-b-0 hover:bg-(--netz-accent-soft)"
									class:bg-(--netz-accent-soft)={selectedFund?.id === fund.id && panelOpen}
									onclick={() => openPanel(fund)}
								>
									<td class="px-4 py-3">
										<div>
											<p class="font-medium text-(--netz-text-primary)">{fund.name}</p>
											{#if fund.subcategory}
												<p class="mt-0.5 text-xs text-(--netz-text-muted)">{fund.subcategory}</p>
											{/if}
										</div>
									</td>
									<td class="px-4 py-3 text-(--netz-text-secondary)">{fund.manager ?? "—"}</td>
									<td class="px-4 py-3 text-right font-mono text-(--netz-text-primary)">{formatAum(fund.aum)}</td>
									<td class="px-4 py-3">
										{#if fund.strategy}
											<span class="inline-flex items-center rounded-(--netz-radius-pill) px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]" style={getStrategyStyle(fund.strategy)}>{fund.strategy}</span>
										{:else}
											<span class="text-(--netz-text-muted)">—</span>
										{/if}
									</td>
									<td class="px-4 py-3">
										<span class="inline-flex items-center gap-1.5 rounded-(--netz-radius-pill) px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]" style={getStatusStyle(fund.status)}>
											<span class="h-1.5 w-1.5 rounded-full" style="background-color: currentColor;"></span>
											{getStatusLabel(fund.status)}
										</span>
									</td>
									<td class="px-4 py-3">
										<span class="inline-flex items-center gap-1.5 rounded-(--netz-radius-pill) px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]" style={getDDReportStyle(fund.dd_report_status)}>
											{#if fund.dd_report_status === "generating"}
												<span class="h-1.5 w-1.5 animate-spin rounded-full border border-current border-t-transparent"></span>
											{:else}
												<span class="h-1.5 w-1.5 rounded-full" style="background-color: currentColor;"></span>
											{/if}
											{getDDReportLabel(fund.dd_report_status)}
										</span>
									</td>
									<td class="px-4 py-3 text-right">
										{#if fund.score !== null}
											<span class="font-mono text-sm font-semibold" style="color: {fund.score >= 7 ? 'var(--netz-success)' : fund.score >= 5 ? 'var(--netz-warning)' : 'var(--netz-danger)'};">
												{formatNumber(fund.score, 1, "en-US")}
											</span>
										{:else}
											<span class="text-(--netz-text-muted)">—</span>
										{/if}
									</td>
									<td class="px-4 py-3 text-(--netz-text-muted)">{formatDate(fund.updated_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<EmptyState
					title="No funds found"
					message={activeStatusTab === "todos" ? "Add funds to the universe to get started." : "No funds in this category at the moment."}
					actionLabel={activeStatusTab === "todos" ? "Add Fund" : undefined}
				/>
			{/if}
		</div>
	{/if}
</div>

<FundDetailPanel fund={selectedFund} open={panelOpen} onClose={closePanel} />
