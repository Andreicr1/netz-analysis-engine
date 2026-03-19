<!--
  @component DealPerformancePanel
  Deal performance KPIs derived from cashflow ledger.
  Displays MOIC, total invested/received, net cashflow, and cash-to-cash days.
  Manual refresh only — no auto-refresh.
-->
<script lang="ts">
	import { MetricCard, Button } from "@netz/ui";
	import { formatCurrency, formatNumber, formatRatio, plColor } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	// ── Type matching DealPerformanceOut from api.d.ts ──
	interface DealPerformanceOut {
		deal_id: string;
		total_invested: number;
		total_received: number;
		net_cashflow: number;
		moic: number | null;
		cash_to_cash_days: number | null;
		cashflow_count: number;
	}

	let {
		fundId,
		dealId,
		initialPerformance = null,
	}: {
		fundId: string;
		dealId: string;
		initialPerformance?: DealPerformanceOut | null;
	} = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── State ──
	let performance = $state<DealPerformanceOut | null>(null);
	$effect(() => {
		if (initialPerformance !== undefined) {
			performance = initialPerformance;
		}
	});
	let loading = $state(false);
	let error = $state<string | null>(null);

	// ── Derived display values ──
	let netCashflowColor = $derived(
		performance ? plColor(performance.net_cashflow) : "var(--netz-text-primary)",
	);

	async function refresh() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.get<DealPerformanceOut>(
				`/funds/${fundId}/deals/${dealId}/performance`,
			);
			performance = result;
		} catch (e) {
			error = e instanceof Error ? e.message : "Falha ao carregar performance.";
		} finally {
			loading = false;
		}
	}
</script>

<div class="space-y-4">
	<!-- Header with refresh button -->
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-lg font-semibold text-[var(--netz-text-primary)]">Performance</h3>
			<p class="text-sm text-[var(--netz-text-muted)]">
				Métricas calculadas a partir dos cashflows registrados.
			</p>
		</div>
		<Button variant="outline" onclick={refresh} disabled={loading}>
			{loading ? "Atualizando..." : "Atualizar"}
		</Button>
	</div>

	{#if error}
		<div
			class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]"
		>
			{error}
		</div>
	{/if}

	{#if performance}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			<MetricCard
				label="Total Investido"
				value={formatCurrency(performance.total_invested)}
				sublabel="Desembolsos + Chamadas de Capital"
			/>

			<MetricCard
				label="Total Recebido"
				value={formatCurrency(performance.total_received)}
				sublabel="Amortizações + Distribuições + Juros"
			/>

			<MetricCard
				label="Cashflow Líquido"
				value={formatCurrency(performance.net_cashflow)}
				sublabel="Recebido − Investido − Taxas"
				class="border-l-[3px]"
			/>

			<MetricCard
				label="MOIC"
				value={performance.moic != null ? formatRatio(performance.moic) : "—"}
				sublabel={performance.moic != null ? "Multiple on Invested Capital" : "Sem retornos registrados"}
			/>

			<MetricCard
				label="Cash-to-Cash"
				value={performance.cash_to_cash_days != null
					? `${formatNumber(performance.cash_to_cash_days, 0)} dias`
					: "—"}
				sublabel="Primeiro desembolso → primeiro retorno"
			/>

			<MetricCard
				label="Cashflows"
				value={formatNumber(performance.cashflow_count, 0)}
				sublabel="Entradas registradas no ledger"
			/>
		</div>
	{:else if !loading}
		<div
			class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-8 text-center"
		>
			<p class="text-sm text-[var(--netz-text-muted)]">
				Clique em <strong>Atualizar</strong> para carregar as métricas de performance.
			</p>
		</div>
	{:else}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each Array(5) as _, i (i)}
				<div
					class="h-24 animate-pulse rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-alt)]"
				></div>
			{/each}
		</div>
	{/if}
</div>
