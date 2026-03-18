<!--
  Model Portfolios — sidebar list + inline detail.
  Figma frame "Model Portfolios com track-record" (node 1:5)
-->
<script lang="ts">
	import {
		EmptyState, PageHeader, StatusBadge, MetricCard, SectionCard,
		UtilizationBar, PeriodSelector, Dialog, Button,
	} from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import { page } from "$app/state";
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type ModelPortfolio = {
		id: string;
		profile: string;
		display_name: string;
		description: string | null;
		benchmark_composite: string | null;
		inception_date: string | null;
		inception_nav: number;
		status: string;
		created_at: string;
	};

	let portfolios = $state.raw((data.modelPortfolios ?? []) as ModelPortfolio[]);

	// Selected portfolio from URL param
	const selectedId = $derived(page.url.searchParams.get("portfolio"));
	const selectedPortfolio = $derived(portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null);

	// Detail cache
	let detailCache = $state(new Map<string, Record<string, unknown>>());
	let loadingDetail = $state(false);

	// Load detail on selection change
	$effect(() => {
		if (!selectedPortfolio) return;
		const id = selectedPortfolio.id;
		if (detailCache.has(id)) return;

		loadingDetail = true;
		const api = createClientApiClient(getToken);

		Promise.allSettled([
			api.get(`/model-portfolios/${id}/track-record`),
		]).then(([trackRecord]) => {
			const detail: Record<string, unknown> = {};
			if (trackRecord.status === "fulfilled") detail.trackRecord = trackRecord.value;
			detailCache.set(id, detail);
			detailCache = new Map(detailCache);
			loadingDetail = false;
		});
	});

	const currentDetail = $derived(selectedPortfolio ? detailCache.get(selectedPortfolio.id) : null);

	function selectPortfolio(id: string) {
		goto(`?portfolio=${id}`, { replaceState: true, noScroll: true });
	}

	// Profile badge colors
	const profileColors: Record<string, string> = {
		conservative: "var(--netz-success)",
		moderate: "var(--netz-info)",
		growth: "var(--netz-danger)",
	};

	// ── Create Model Portfolio Dialog ──
	let showCreate = $state(false);
	let creating = $state(false);
	let createError = $state<string | null>(null);
	let createForm = $state({
		display_name: "",
		profile: "moderate",
		benchmark_composite: "",
		description: "",
	});

	function resetCreateForm() {
		createForm = { display_name: "", profile: "moderate", benchmark_composite: "", description: "" };
		createError = null;
	}

	async function createPortfolio() {
		creating = true;
		createError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/model-portfolios", {
				display_name: createForm.display_name.trim(),
				profile: createForm.profile,
				benchmark_composite: createForm.benchmark_composite.trim() || null,
				description: createForm.description.trim() || null,
			});
			showCreate = false;
			resetCreateForm();
			await invalidateAll();
		} catch (e) {
			createError = e instanceof Error ? e.message : "Failed to create";
		} finally {
			creating = false;
		}
	}

	// ── Actions on selected portfolio ──
	let actionLoading = $state<string | null>(null);
	let actionError = $state<string | null>(null);
	let showAllocateConfirm = $state(false);
	let showRebalanceConfirm = $state(false);
	let backtestResult = $state<Record<string, unknown> | null>(null);

	async function runBacktest() {
		if (!selectedPortfolio) return;
		actionLoading = "backtest";
		actionError = null;
		backtestResult = null;
		try {
			const api = createClientApiClient(getToken);
			backtestResult = await api.get(`/model-portfolios/${selectedPortfolio.id}/backtest`);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Backtest failed";
		} finally {
			actionLoading = null;
		}
	}

	async function allocateToModel() {
		if (!selectedPortfolio) return;
		actionLoading = "allocate";
		showAllocateConfirm = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/model-portfolios/${selectedPortfolio.id}/allocate`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Allocation failed";
		} finally {
			actionLoading = null;
		}
	}

	async function rebalanceModel() {
		if (!selectedPortfolio) return;
		actionLoading = "rebalance";
		showRebalanceConfirm = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/model-portfolios/${selectedPortfolio.id}/rebalance`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rebalance failed";
		} finally {
			actionLoading = null;
		}
	}
</script>

<div class="flex h-full">
	<!-- Sidebar: portfolio list (240px) -->
	<div class="flex w-60 shrink-0 flex-col border-r border-[var(--netz-border)] bg-[var(--netz-surface)]">
		<div class="flex items-center justify-between border-b border-[var(--netz-border)] px-4 py-3">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-[var(--netz-text-muted)]">Portfólios</h2>
			<button
				class="rounded-md bg-[var(--netz-brand-primary)] px-2.5 py-1 text-xs font-medium text-white hover:opacity-90"
				onclick={() => { resetCreateForm(); showCreate = true; }}
			>
				+ Novo
			</button>
		</div>

		<div class="flex-1 overflow-y-auto p-2">
			{#each portfolios as portfolio (portfolio.id)}
				<button
					class="mb-1 w-full rounded-lg p-3 text-left transition-colors {portfolio.id === selectedPortfolio?.id
						? 'border-l-2 border-[var(--netz-brand-primary)] bg-[var(--netz-surface-alt)]'
						: 'hover:bg-[var(--netz-surface-alt)]'}"
					onclick={() => selectPortfolio(portfolio.id)}
				>
					<div class="flex items-center justify-between">
						<p class="text-sm font-semibold text-[var(--netz-text-primary)]">{portfolio.display_name}</p>
						<span
							class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold capitalize"
							style="color: {profileColors[portfolio.profile] ?? 'var(--netz-text-muted)'}; border: 1px solid currentColor;"
						>
							{portfolio.profile}
						</span>
					</div>
					<div class="mt-1 flex items-center gap-2 text-xs text-[var(--netz-text-muted)]">
						<span>NAV {portfolio.inception_nav.toFixed(0)}</span>
						<span>·</span>
						<StatusBadge status={portfolio.status} />
					</div>
				</button>
			{/each}
		</div>
	</div>

	<!-- Main: portfolio detail -->
	<div class="flex-1 overflow-y-auto p-6">
		{#if selectedPortfolio}
			<!-- Header -->
			<div class="mb-6 flex items-start justify-between">
				<div>
					<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">{selectedPortfolio.display_name}</h1>
					<p class="mt-1 text-sm text-[var(--netz-text-muted)]">
						Model Portfolio · {selectedPortfolio.benchmark_composite ?? "—"}
						{#if selectedPortfolio.inception_date}
							· Última revisão: {selectedPortfolio.inception_date}
						{/if}
					</p>
				</div>
				<div class="flex gap-2">
					<ActionButton
						size="sm"
						variant="outline"
						onclick={runBacktest}
						loading={actionLoading === "backtest"}
						loadingText="Running..."
					>
						Backtest
					</ActionButton>
					<ActionButton
						size="sm"
						variant="outline"
						onclick={() => showRebalanceConfirm = true}
						loading={actionLoading === "rebalance"}
						loadingText="..."
					>
						Rebalancear
					</ActionButton>
					<ActionButton
						size="sm"
						onclick={() => showAllocateConfirm = true}
						loading={actionLoading === "allocate"}
						loadingText="..."
					>
						Construir portfólio
					</ActionButton>
				</div>
			</div>

			<!-- 6 KPI Cards -->
			<div class="mb-6 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
				<MetricCard label="NAV Atual" value="Base {selectedPortfolio.inception_nav.toFixed(0)}" />
				<MetricCard label="YTD" value="—" status="ok" />
				<MetricCard label="CVaR 95%" value="—" status="warn" sublabel="lim: —" />
				<MetricCard label="Sharpe" value="—" />
				<MetricCard label="Vol Anual" value="—" sublabel="rolling 12M" />
				<MetricCard label="Max Drawdown" value="—" status="breach" />
			</div>

			<!-- Track Record -->
			<SectionCard title="Track-Record — Retornos Periódicos" class="mb-6">
				<EmptyState
					title="Retornos periódicos indisponíveis"
					message="Retornos periódicos serão calculados quando dados de NAV histórico estiverem disponíveis."
				/>
			</SectionCard>

			<!-- Allocation by Block -->
			<SectionCard title="Alocação por Bloco" class="mb-6">
				<EmptyState
					title="Dados de alocação"
					message="Alocação por bloco será exibida quando a seleção de fundos estiver configurada."
				/>
			</SectionCard>

			<!-- Stress Scenarios -->
			<SectionCard title="Stress Scenarios">
				<EmptyState
					title="Cenários de stress"
					message="Cenários de stress serão exibidos quando dados de track-record estiverem disponíveis."
				/>
			</SectionCard>
		{:else}
			<EmptyState
				title="Nenhum portfólio"
				message="Crie um model portfolio para começar."
			/>
		{/if}

		{#if actionError}
			<div class="mt-4 rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
				{actionError}
				<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
			</div>
		{/if}

		{#if backtestResult}
			<SectionCard title="Backtest Results" class="mt-4">
				<div class="space-y-2">
					{#each Object.entries(backtestResult) as [key, value]}
						<div class="flex items-center justify-between text-sm">
							<span class="text-[var(--netz-text-secondary)]">{key}</span>
							<span class="font-mono text-[var(--netz-text-primary)]">{typeof value === "number" ? value.toFixed(4) : String(value ?? "—")}</span>
						</div>
					{/each}
				</div>
			</SectionCard>
		{/if}
	</div>
</div>

<!-- Create Model Portfolio Dialog -->
<Dialog bind:open={showCreate} title="Create Model Portfolio">
	<form onsubmit={(e) => { e.preventDefault(); createPortfolio(); }} class="space-y-4">
		<FormField label="Name" required>
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={createForm.display_name}
				placeholder="e.g. Conservative Income"
			/>
		</FormField>
		<FormField label="Profile" required>
			<select
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={createForm.profile}
			>
				<option value="conservative">Conservative</option>
				<option value="moderate">Moderate</option>
				<option value="growth">Growth</option>
			</select>
		</FormField>
		<FormField label="Benchmark Composite">
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={createForm.benchmark_composite}
				placeholder="e.g. 60% IVV + 40% AGG"
			/>
		</FormField>
		<FormField label="Description">
			<textarea
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={createForm.description}
				rows={2}
			></textarea>
		</FormField>
		{#if createError}
			<p class="text-sm text-[var(--netz-status-error)]">{createError}</p>
		{/if}
		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreate = false}>Cancel</Button>
			<ActionButton onclick={createPortfolio} loading={creating} loadingText="Creating..." disabled={!createForm.display_name.trim()}>
				Create
			</ActionButton>
		</div>
	</form>
</Dialog>

<ConfirmDialog
	bind:open={showAllocateConfirm}
	title="Allocate to Model"
	message="This will allocate funds to the selected model portfolio. Continue?"
	confirmLabel="Allocate"
	confirmVariant="default"
	onConfirm={allocateToModel}
	onCancel={() => showAllocateConfirm = false}
/>

<ConfirmDialog
	bind:open={showRebalanceConfirm}
	title="Rebalance Model Portfolio"
	message="This will trigger a rebalance to realign with target allocations. Continue?"
	confirmLabel="Rebalance"
	confirmVariant="default"
	onConfirm={rebalanceModel}
	onCancel={() => showRebalanceConfirm = false}
/>
