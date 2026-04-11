<!--
  FundsView — Institutional Fund Universe.
  Strict brutalism: 1px grid gaps, rounded-none, text-11px font-mono.
-->
<script lang="ts">
	import { EmptyState, formatAUM as formatSharedAUM, formatDate as formatSharedDate, formatNumber } from "@investintell/ui";
	import { Badge } from "@investintell/ui/components/ui/badge";
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Skeleton } from "@investintell/ui/components/ui/skeleton";
	import { Spinner } from "@investintell/ui/components/ui/spinner";
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
		{ value: "todos", label: "ALL" },
		{ value: "aprovados", label: "APPROVED" },
		{ value: "dd_pendente", label: "DD PENDING" },
		{ value: "watchlist", label: "WATCHLIST" },
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

	// Helpers
	function formatAum(value: number | null): string { return formatSharedAUM(value, "BRL", "pt-BR"); }
	function formatDate(value: string | null): string { return formatSharedDate(value, "short", "pt-BR"); }

	fetchData();
</script>

<div class="flex flex-col h-full bg-[#222] font-mono text-[11px] tabular-nums">
	{#if loading}
		<div class="flex flex-col gap-[1px]">
			{#each Array.from({length: 8}, (_, i) => i) as i (i)}
				<div class="h-10 bg-black animate-pulse"></div>
			{/each}
		</div>
	{:else}
		<div class="bg-black p-2 flex items-center justify-between border-b border-[#222]">
			<h3 class="text-[10px] font-black uppercase tracking-widest text-white">FUND UNIVERSE [N={funds.length}]</h3>
			<button 
				class="bg-white text-black px-3 py-1 text-[10px] font-black uppercase tracking-widest hover:bg-(--ii-brand-primary) hover:text-white transition-colors"
				onclick={() => {}}
			>
				+ ADD_ENTITY
			</button>
		</div>

		<Tabs.Root bind:value={activeStatusTab} class="flex-1 flex flex-col min-h-0">
			<!-- Brutalist Status Tabs -->
			<Tabs.List class="flex w-full justify-start rounded-none bg-[#222] p-0 h-auto gap-[1px] border-b border-[#222]">
				{#each statusTabs as tab (tab.value)}
					<Tabs.Trigger 
						value={tab.value} 
						class="rounded-none bg-black px-4 py-2 text-[10px] font-bold uppercase tracking-widest data-[state=active]:bg-[#222] data-[state=active]:text-white border-none"
					>
						{tab.label}
						{#if tabCounts[tab.value] > 0}
							<span class="ml-2 text-[9px] opacity-50">[{tabCounts[tab.value]}]</span>
						{/if}
					</Tabs.Trigger>
				{/each}
			</Tabs.List>

			{#if filteredFunds.length > 0}
				<div class="flex-1 overflow-auto bg-[#222]">
					<table class="w-full border-collapse">
						<thead class="sticky top-0 z-10 bg-[#222]">
							<tr>
								<th class="bg-black px-2 py-2 text-left text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">ENTITY_NAME</th>
								<th class="bg-black px-2 py-2 text-left text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">MANAGER</th>
								<th class="bg-black px-2 py-2 text-right text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">AUM_BRL</th>
								<th class="bg-black px-2 py-2 text-left text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">STRATEGY</th>
								<th class="bg-black px-2 py-2 text-left text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">STATUS</th>
								<th class="bg-black px-2 py-2 text-left text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">DD_PIPELINE</th>
								<th class="bg-black px-2 py-2 text-right text-[9px] font-black uppercase text-[#71717a] border-r border-[#222]">SCORE</th>
								<th class="bg-black px-2 py-2 text-left text-[9px] font-black uppercase text-[#71717a]">UPDATED</th>
							</tr>
						</thead>
						<tbody class="bg-[#222] gap-[1px]">
							{#each filteredFunds as fund (fund.id)}
								<tr
									class="cursor-pointer bg-black hover:bg-[#111] group {selectedFund?.id === fund.id && panelOpen ? 'bg-[#111]' : ''}"
									onclick={() => openPanel(fund)}
								>
									<td class="px-2 py-1.5 border-r border-[#222] font-black uppercase truncate max-w-[250px]">{fund.name}</td>
									<td class="px-2 py-1.5 border-r border-[#222] text-[#71717a] uppercase truncate max-w-[150px]">{fund.manager ?? "—"}</td>
									<td class="px-2 py-1.5 border-r border-[#222] text-right font-black">{formatAum(fund.aum)}</td>
									<td class="px-2 py-1.5 border-r border-[#222] truncate max-w-[120px]">
										{#if fund.strategy}
											<span class="text-[9px] font-black uppercase tracking-tighter text-(--ii-brand-primary)">{fund.strategy}</span>
										{:else}
											<span class="text-[#3f3f46]">—</span>
										{/if}
									</td>
									<td class="px-2 py-1.5 border-r border-[#222]">
										<div class="flex items-center gap-1">
											<div class="w-1.5 h-1.5 {fund.status === 'aprovado' ? 'bg-(--ii-success)' : fund.status === 'watchlist' ? 'bg-(--ii-warning)' : 'bg-[#3f3f46]'}"></div>
											<span class="text-[9px] font-black uppercase">{fund.status?.toUpperCase() ?? "PENDING"}</span>
										</div>
									</td>
									<td class="px-2 py-1.5 border-r border-[#222]">
										<span class="text-[9px] font-black uppercase {fund.dd_report_status === 'complete' ? 'text-(--ii-success)' : 'text-[#71717a]'}">
											{fund.dd_report_status?.toUpperCase() ?? "PENDING"}
										</span>
									</td>
									<td class="px-2 py-1.5 border-r border-[#222] text-right">
										{#if fund.score !== null}
											<span class="font-black text-[12px] {fund.score >= 7 ? 'text-(--ii-success)' : fund.score >= 5 ? 'text-(--ii-warning)' : 'text-(--ii-danger)'}">
												{formatNumber(fund.score, 1, "en-US")}
											</span>
										{:else}
											<span class="text-[#3f3f46]">—</span>
										{/if}
									</td>
									<td class="px-2 py-1.5 text-[#71717a] text-[9px]">{formatDate(fund.updated_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<div class="flex-1 bg-black flex items-center justify-center border border-[#222]">
					<p class="text-[10px] font-black uppercase tracking-widest text-[#3f3f46]">ZERO ENTITIES IN CURRENT VIEW</p>
				</div>
			{/if}
		</Tabs.Root>
	{/if}
</div>

<FundDetailPanel fund={selectedFund} open={panelOpen} onClose={closePanel} />
