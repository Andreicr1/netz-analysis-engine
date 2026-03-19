<!--
  Model Portfolios — sidebar list + inline detail.
  Figma frame "Model Portfolios com track-record" (node 1:5)
-->
<script lang="ts">
	import {
		Badge, EmptyState, PageHeader, StatusBadge, MetricCard, SectionCard,
		UtilizationBar, PeriodSelector, Dialog, Button, Input, Select, Textarea, formatDate, formatNumber,
	} from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import { page } from "$app/state";
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

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

	let portfolios = $derived((data.modelPortfolios ?? []) as ModelPortfolio[]);

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

<div class="flex h-full bg-transparent">
	<!-- Sidebar: portfolio list (240px) -->
	<div class="flex w-72 shrink-0 flex-col border-r border-(--netz-border-subtle) bg-(--netz-surface-panel)">
		<div class="flex items-center justify-between border-b border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-5 py-4">
			<div>
				<p class="netz-ui-kicker">Library</p>
				<h2 class="mt-2 text-sm font-semibold text-(--netz-text-primary)">Model Portfolios</h2>
			</div>
			<Button
				size="sm"
				onclick={() => { resetCreateForm(); showCreate = true; }}
			>
				+ New
			</Button>
		</div>

		<div class="flex-1 overflow-y-auto p-3">
			{#each portfolios as portfolio (portfolio.id)}
				<button
					class="mb-2 w-full rounded-(--netz-radius-lg) border p-4 text-left transition-[background-color,border-color,box-shadow] duration-(--netz-duration-fast) {portfolio.id === selectedPortfolio?.id
						? 'border-(--netz-border) bg-(--netz-surface-elevated) shadow-(--netz-shadow-2)'
						: 'border-transparent bg-transparent hover:border-(--netz-border-subtle) hover:bg-(--netz-accent-soft)'}"
					onclick={() => selectPortfolio(portfolio.id)}
				>
					<div class="flex items-center justify-between">
						<p class="text-sm font-semibold text-(--netz-text-primary)">{portfolio.display_name}</p>
						<Badge variant="secondary" class="capitalize">
							{portfolio.profile}
						</Badge>
					</div>
					<div class="mt-1 flex items-center gap-2 text-xs text-(--netz-text-muted)">
						<span>NAV {formatNumber(portfolio.inception_nav, 0, "en-US")}</span>
						<span>·</span>
						<StatusBadge status={portfolio.status} resolve={resolveWealthStatus} />
					</div>
				</button>
			{/each}
		</div>
	</div>

	<!-- Main: portfolio detail -->
	<div class="flex-1 overflow-y-auto p-(--netz-space-page-gutter)">
		{#if selectedPortfolio}
			<!-- Header -->
			<PageHeader title={selectedPortfolio.display_name} class="pt-0">
				{#snippet actions()}
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
						Rebalance
					</ActionButton>
					<ActionButton
						size="sm"
						onclick={() => showAllocateConfirm = true}
						loading={actionLoading === "allocate"}
						loadingText="..."
					>
						Build Portfolio
					</ActionButton>
				{/snippet}
			</PageHeader>
			<p class="mb-6 mt-1 text-sm text-(--netz-text-muted)">
				Model Portfolio · {selectedPortfolio.benchmark_composite ?? "—"}
				{#if selectedPortfolio.inception_date}
					· Last review: {formatDate(selectedPortfolio.inception_date)}
				{/if}
			</p>

			<!-- 6 KPI Cards -->
			<div class="mb-6 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
				<MetricCard label="Current NAV" value="Base {formatNumber(selectedPortfolio.inception_nav, 0, 'en-US')}" />
				<MetricCard label="YTD" value="—" status="ok" />
				<MetricCard label="CVaR 95%" value="—" status="warn" sublabel="lim: —" />
				<MetricCard label="Sharpe" value="—" />
				<MetricCard label="Annual Vol" value="—" sublabel="rolling 12M" />
				<MetricCard label="Max Drawdown" value="—" status="breach" />
			</div>

			<!-- Track Record -->
			<SectionCard title="Track Record — Periodic Returns" class="mb-6">
				<EmptyState
					title="Periodic returns unavailable"
					message="Periodic returns will be calculated when historical NAV data is available."
				/>
			</SectionCard>

			<!-- Allocation by Block -->
			<SectionCard title="Allocation by Block" class="mb-6">
				<EmptyState
					title="Allocation data"
					message="Block allocation will appear when fund selection is configured."
				/>
			</SectionCard>

			<!-- Stress Scenarios -->
			<SectionCard title="Stress Scenarios">
				<EmptyState
					title="Stress scenarios"
					message="Stress scenarios will appear when track-record data is available."
				/>
			</SectionCard>
		{:else}
			<EmptyState
				title="No portfolios"
				message="Create a model portfolio to get started."
			/>
		{/if}

		{#if actionError}
			<div class="mt-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{actionError}
				<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
			</div>
		{/if}

		{#if backtestResult}
			<SectionCard title="Backtest Results" class="mt-4">
				<div class="space-y-2">
					{#each Object.entries(backtestResult) as [key, value]}
						<div class="flex items-center justify-between text-sm">
							<span class="text-(--netz-text-secondary)">{key}</span>
							<span class="font-mono text-(--netz-text-primary)">{typeof value === "number" ? formatNumber(value, 4, "en-US") : String(value ?? "—")}</span>
						</div>
					{/each}
				</div>
			</SectionCard>
		{/if}
	</div>
</div>

<!-- Create Model Portfolio Dialog -->
<Dialog bind:open={showCreate}>
	<form onsubmit={(e) => { e.preventDefault(); createPortfolio(); }} class="space-y-4">
		<div class="space-y-2">
			<p class="netz-ui-kicker">Create</p>
			<h2 class="text-lg font-semibold tracking-[-0.02em] text-(--netz-text-primary)">
				Create Model Portfolio
			</h2>
		</div>
		<FormField label="Name" required>
			<Input
				type="text"
				value={createForm.display_name}
				oninput={(event) => {
					createForm = { ...createForm, display_name: (event.currentTarget as HTMLInputElement).value };
				}}
				placeholder="e.g. Conservative Income"
			/>
		</FormField>
		<FormField label="Profile" required>
			<Select
				bind:value={createForm.profile}
				options={[
					{ value: "conservative", label: "Conservative" },
					{ value: "moderate", label: "Moderate" },
					{ value: "growth", label: "Growth" },
				]}
			>
			</Select>
		</FormField>
		<FormField label="Benchmark Composite">
			<Input
				type="text"
				value={createForm.benchmark_composite}
				oninput={(event) => {
					createForm = {
						...createForm,
						benchmark_composite: (event.currentTarget as HTMLInputElement).value,
					};
				}}
				placeholder="e.g. 60% IVV + 40% AGG"
			/>
		</FormField>
		<FormField label="Description">
			<Textarea
				value={createForm.description}
				oninput={(event) => {
					createForm = { ...createForm, description: (event.currentTarget as HTMLTextAreaElement).value };
				}}
				rows={2}
			></Textarea>
		</FormField>
		{#if createError}
			<p class="text-sm text-(--netz-status-error)">{createError}</p>
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
