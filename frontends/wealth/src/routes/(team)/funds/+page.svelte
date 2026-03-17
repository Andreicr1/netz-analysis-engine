<!--
  Fund Universe — Figma spec "Fund Universe + DD Pipeline" (node 1:6).
  Status tabs (Todos / Aprovados / DD Pendente / Watchlist) + institutional table
  + ContextPanel side panel with FundDetailPanel.
-->
<script lang="ts">
	import { PageHeader, EmptyState } from "@netz/ui";
	import FundDetailPanel from "$lib/components/FundDetailPanel.svelte";
	import type { PageData } from "./$types";

	// ── Types ──────────────────────────────────────────────────────────────

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

	let { data }: { data: PageData } = $props();

	// ── Data ────────────────────────────────────────────────────────────────

	let funds = $state.raw((data.funds ?? []) as FundRow[]);

	// ── Status tabs ─────────────────────────────────────────────────────────

	type StatusTab = "todos" | "aprovados" | "dd_pendente" | "watchlist";

	let activeStatusTab = $state<StatusTab>("todos");

	const statusTabs: { value: StatusTab; label: string }[] = [
		{ value: "todos", label: "Todos" },
		{ value: "aprovados", label: "Aprovados" },
		{ value: "dd_pendente", label: "DD Pendente" },
		{ value: "watchlist", label: "Watchlist" },
	];

	// Count per tab
	let tabCounts = $derived({
		todos: funds.length,
		aprovados: funds.filter((f) => f.status === "aprovado").length,
		dd_pendente: funds.filter((f) => f.dd_report_status === "pendente" || f.status === "dd_pendente").length,
		watchlist: funds.filter((f) => f.status === "watchlist").length,
	});

	// Filtered funds based on active tab
	let filteredFunds = $derived.by((): FundRow[] => {
		switch (activeStatusTab) {
			case "aprovados":
				return funds.filter((f) => f.status === "aprovado");
			case "dd_pendente":
				return funds.filter((f) => f.dd_report_status === "pendente" || f.status === "dd_pendente");
			case "watchlist":
				return funds.filter((f) => f.status === "watchlist");
			default:
				return funds;
		}
	});

	// ── Side panel ──────────────────────────────────────────────────────────

	let selectedFund = $state<FundRow | null>(null);
	let panelOpen = $state(false);

	function openPanel(fund: FundRow) {
		selectedFund = fund;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		// Delay clearing so close animation completes
		setTimeout(() => {
			selectedFund = null;
		}, 220);
	}

	// ── Strategy badge colors ────────────────────────────────────────────────

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

	// ── Status badge helpers ─────────────────────────────────────────────────

	function getStatusStyle(status: string | null): string {
		switch (status) {
			case "aprovado":
				return "background: color-mix(in srgb, var(--netz-success) 15%, transparent); color: var(--netz-success);";
			case "watchlist":
				return "background: color-mix(in srgb, var(--netz-warning) 15%, transparent); color: var(--netz-warning);";
			case "dd_pendente":
			case "pendente":
				return "background: color-mix(in srgb, var(--netz-text-muted) 15%, transparent); color: var(--netz-text-muted);";
			default:
				return "background: color-mix(in srgb, var(--netz-text-muted) 15%, transparent); color: var(--netz-text-muted);";
		}
	}

	function getStatusLabel(status: string | null): string {
		switch (status) {
			case "aprovado": return "Aprovado";
			case "watchlist": return "Watchlist";
			case "dd_pendente": return "Pendente DD";
			default: return status ?? "—";
		}
	}

	function getDDReportStyle(ddStatus: string | null): string {
		switch (ddStatus) {
			case "complete":
				return "background: color-mix(in srgb, var(--netz-success) 15%, transparent); color: var(--netz-success);";
			case "generating":
				return "background: color-mix(in srgb, var(--netz-brand-primary) 15%, transparent); color: var(--netz-brand-primary);";
			case "pendente":
			default:
				return "background: color-mix(in srgb, var(--netz-text-muted) 15%, transparent); color: var(--netz-text-muted);";
		}
	}

	function getDDReportLabel(ddStatus: string | null): string {
		switch (ddStatus) {
			case "complete": return "Completo";
			case "generating": return "Gerando…";
			case "pendente": return "Pendente";
			default: return "Pendente";
		}
	}

	// ── Format helpers ───────────────────────────────────────────────────────

	function formatAum(value: number | null): string {
		if (value === null) return "—";
		if (value >= 1_000_000_000) return `R$ ${(value / 1_000_000_000).toFixed(1)}B`;
		if (value >= 1_000_000) return `R$ ${(value / 1_000_000).toFixed(0)}M`;
		return `R$ ${value.toLocaleString("pt-BR")}`;
	}

	function formatDate(value: string | null): string {
		if (!value) return "—";
		return new Date(value).toLocaleDateString("pt-BR", {
			day: "2-digit",
			month: "short",
			year: "numeric",
		});
	}
</script>

<div class="space-y-0 p-6">
	<!-- Page Header -->
	<PageHeader title="Fund Universe">
		{#snippet actions()}
			<button
				class="inline-flex h-9 items-center gap-1.5 rounded-md bg-[var(--netz-brand-primary)] px-4 text-sm font-medium text-white transition-colors hover:opacity-90 active:opacity-80"
			>
				<svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
					<path d="M10 4v12M4 10h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
				</svg>
				Adicionar fundo
			</button>
		{/snippet}
	</PageHeader>

	<!-- Status Tabs -->
	<div class="flex items-center gap-1 border-b border-[var(--netz-border)] pb-0">
		{#each statusTabs as tab (tab.value)}
			<button
				class="relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors"
				class:text-[var(--netz-brand-primary)]={activeStatusTab === tab.value}
				class:text-[var(--netz-text-muted)]={activeStatusTab !== tab.value}
				onclick={() => (activeStatusTab = tab.value)}
			>
				{tab.label}
				<!-- Count badge -->
				{#if tabCounts[tab.value] > 0}
					<span
						class="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-xs font-semibold"
						class:bg-[var(--netz-brand-primary)]={activeStatusTab === tab.value}
						class:text-white={activeStatusTab === tab.value}
						class:bg-[var(--netz-surface-inset)]={activeStatusTab !== tab.value}
						class:text-[var(--netz-text-muted)]={activeStatusTab !== tab.value}
					>
						{tabCounts[tab.value]}
					</span>
				{/if}
				<!-- Active underline -->
				{#if activeStatusTab === tab.value}
					<span class="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--netz-brand-primary)]"></span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Fund Table -->
	<div class="rounded-b-lg border-x border-b border-[var(--netz-border)] bg-[var(--netz-surface-elevated)]">
		{#if filteredFunds.length > 0}
			<div class="overflow-x-auto">
				<table class="w-full min-w-[800px] text-sm">
					<thead>
						<tr class="border-b border-[var(--netz-border)]">
							<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								Fundo
							</th>
							<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								Gestor
							</th>
							<th class="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								AUM
							</th>
							<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								Estratégia
							</th>
							<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								Status
							</th>
							<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								DD Report
							</th>
							<th class="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								Score
							</th>
							<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-[var(--netz-text-muted)]">
								Atualizado
							</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredFunds as fund (fund.id)}
							<tr
								class="cursor-pointer border-b border-[var(--netz-border)] transition-colors last:border-b-0 hover:bg-[var(--netz-surface-inset)]"
								class:bg-[var(--netz-surface-inset)]={selectedFund?.id === fund.id && panelOpen}
								onclick={() => openPanel(fund)}
							>
								<!-- Fundo: name + subcategory -->
								<td class="px-4 py-3">
									<div>
										<p class="font-medium text-[var(--netz-text-primary)]">{fund.name}</p>
										{#if fund.subcategory}
											<p class="mt-0.5 text-xs text-[var(--netz-text-muted)]">{fund.subcategory}</p>
										{/if}
									</div>
								</td>

								<!-- Gestor -->
								<td class="px-4 py-3 text-[var(--netz-text-secondary)]">
									{fund.manager ?? "—"}
								</td>

								<!-- AUM -->
								<td class="px-4 py-3 text-right font-mono text-[var(--netz-text-primary)]">
									{formatAum(fund.aum)}
								</td>

								<!-- Estratégia badge -->
								<td class="px-4 py-3">
									{#if fund.strategy}
										<span
											class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
											style={getStrategyStyle(fund.strategy)}
										>
											{fund.strategy}
										</span>
									{:else}
										<span class="text-[var(--netz-text-muted)]">—</span>
									{/if}
								</td>

								<!-- Status badge -->
								<td class="px-4 py-3">
									<span
										class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
										style={getStatusStyle(fund.status)}
									>
										<span
											class="h-1.5 w-1.5 rounded-full"
											style="background-color: currentColor;"
										></span>
										{getStatusLabel(fund.status)}
									</span>
								</td>

								<!-- DD Report status -->
								<td class="px-4 py-3">
									<span
										class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
										style={getDDReportStyle(fund.dd_report_status)}
									>
										{#if fund.dd_report_status === "generating"}
											<!-- Spinning dot for generating state -->
											<span class="h-1.5 w-1.5 animate-spin rounded-full border border-current border-t-transparent"></span>
										{:else}
											<span class="h-1.5 w-1.5 rounded-full" style="background-color: currentColor;"></span>
										{/if}
										{getDDReportLabel(fund.dd_report_status)}
									</span>
								</td>

								<!-- Score -->
								<td class="px-4 py-3 text-right">
									{#if fund.score !== null}
										<span
											class="font-mono text-sm font-semibold"
											style="color: {fund.score >= 7 ? 'var(--netz-success)' : fund.score >= 5 ? 'var(--netz-warning)' : 'var(--netz-danger)'};"
										>
											{fund.score.toFixed(1)}
										</span>
									{:else}
										<span class="text-[var(--netz-text-muted)]">—</span>
									{/if}
								</td>

								<!-- Atualizado -->
								<td class="px-4 py-3 text-[var(--netz-text-muted)]">
									{formatDate(fund.updated_at)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<EmptyState
				title="Nenhum fundo encontrado"
				message={activeStatusTab === "todos"
					? "Adicione fundos ao universo para começar."
					: "Nenhum fundo nesta categoria no momento."}
				actionLabel={activeStatusTab === "todos" ? "Adicionar fundo" : undefined}
			/>
		{/if}
	</div>
</div>

<!-- Fund Detail Side Panel -->
<FundDetailPanel
	fund={selectedFund}
	open={panelOpen}
	onClose={closePanel}
/>
