<!--
  Allocation — strategic, tactical, and effective views with profile selector.
-->
<script lang="ts">
	import { DataCard, BarChart, PageHeader, EmptyState, Button, formatNumber, formatPercent } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type AllocationRow = {
		block: string;
		weight: number;
		min_weight: number | null;
		max_weight: number | null;
	};

	type TacticalPosition = {
		block: string;
		overweight: number;
		conviction: number | null;
	};

	type EffectiveRow = {
		block: string;
		strategic_weight: number;
		tactical_overweight: number;
		effective_weight: number;
	};

	let strategic = $derived((data.strategic ?? []) as AllocationRow[]);
	let tactical = $derived((data.tactical ?? []) as TacticalPosition[]);
	let effective = $derived((data.effective ?? []) as EffectiveRow[]);

	let activeProfile = $state(data.profile as string);
	const profiles = ["conservative", "moderate", "growth"];

	type Tab = "strategic" | "tactical" | "effective";
	let activeTab = $state<Tab>("effective");

	function switchProfile(profile: string) {
		activeProfile = profile;
		goto(`/allocation?profile=${profile}`, { invalidateAll: true });
	}

	// Bar chart data
	let strategicChartData = $derived(
		strategic.map((r) => ({ name: r.block, value: r.weight * 100 })),
	);

	let effectiveChartData = $derived(
		effective.map((r) => ({ name: r.block, value: r.effective_weight * 100 })),
	);

	let totalWeight = $derived(
		effective.reduce((sum, r) => sum + r.effective_weight, 0),
	);

	// ── Edit Mode ──
	let editing = $state(false);
	let saving = $state(false);
	let editError = $state<string | null>(null);

	// Editable copies for strategic weights
	let editWeights = $state<Record<string, number>>({});

	function startEditing() {
		editWeights = {};
		for (const row of strategic) {
			editWeights[row.block] = row.weight * 100;
		}
		editError = null;
		editing = true;
	}

	function cancelEditing() {
		editing = false;
		editError = null;
	}

	let editTotal = $derived(
		Object.values(editWeights).reduce((sum, v) => sum + v, 0),
	);

	let editDelta = $derived(Math.abs(editTotal - 100));
	let editValid = $derived(editDelta < 0.1); // must sum to 100%

	function fmtPercentPoint(value: number, decimals = 1): string {
		return `${formatNumber(value, decimals, "en-US")}%`;
	}

	function fmtSignedPercentPoint(value: number, decimals = 1): string {
		const formatted = formatNumber(value, decimals, "en-US");
		return value >= 0 ? `+${formatted}%` : `${formatted}%`;
	}

	async function saveStrategic() {
		if (!editValid) return;
		saving = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const weights: Record<string, number> = {};
			for (const [block, w] of Object.entries(editWeights)) {
				weights[block] = w / 100;
			}
			await api.put(`/allocation/${activeProfile}/strategic`, { weights });
			editing = false;
			await invalidateAll();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to save allocation";
		} finally {
			saving = false;
		}
	}

	// Tactical save
	let editTactical = $state<Record<string, number>>({});
	let editingTactical = $state(false);
	let savingTactical = $state(false);

	function startEditingTactical() {
		editTactical = {};
		for (const pos of tactical) {
			editTactical[pos.block] = pos.overweight * 100;
		}
		editingTactical = true;
	}

	async function saveTactical() {
		savingTactical = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const tilts: Record<string, number> = {};
			for (const [block, w] of Object.entries(editTactical)) {
				tilts[block] = w / 100;
			}
			await api.put(`/allocation/${activeProfile}/tactical`, { tilts });
			editingTactical = false;
			await invalidateAll();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to save tactical allocation";
		} finally {
			savingTactical = false;
		}
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Allocation">
		{#snippet actions()}
			<div class="flex gap-1">
				{#each profiles as profile (profile)}
					<button
						class="rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors {activeProfile === profile
							? 'bg-[var(--netz-primary)] text-white'
							: 'text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]'}"
						onclick={() => switchProfile(profile)}
					>
						{profile}
					</button>
				{/each}
			</div>
		{/snippet}
	</PageHeader>

	<!-- Tab selector -->
	<div class="flex gap-1 border-b border-[var(--netz-border)]">
		{#each (["strategic", "tactical", "effective"] as Tab[]) as tab (tab)}
			<button
				class="border-b-2 px-4 py-2 text-sm font-medium capitalize transition-colors {activeTab === tab
					? 'border-[var(--netz-primary)] text-[var(--netz-primary)]'
					: 'border-transparent text-[var(--netz-text-secondary)] hover:text-[var(--netz-text-primary)]'}"
				onclick={() => activeTab = tab}
			>
				{tab}
			</button>
		{/each}
	</div>

	{#if editError}
		<div class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{editError}
			<button class="ml-2 underline" onclick={() => editError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Strategic View -->
	{#if activeTab === "strategic"}
		{#if strategic.length > 0}
			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
					<div class="mb-4 flex items-center justify-between">
						<h3 class="text-sm font-semibold text-[var(--netz-text-primary)]">Strategic Weights</h3>
						{#if !editing}
							<Button size="sm" variant="outline" onclick={startEditing}>Edit</Button>
						{:else}
							<div class="flex items-center gap-2">
								<span class="text-xs {editValid ? 'text-[var(--netz-success,#22c55e)]' : 'text-[var(--netz-danger,#ef4444)]'}">
									Total: {fmtPercentPoint(editTotal)} {editValid ? "✓" : `(${fmtSignedPercentPoint(editTotal - 100)})`}
								</span>
								<Button size="sm" variant="outline" onclick={cancelEditing}>Cancel</Button>
								<ActionButton size="sm" onclick={saveStrategic} loading={saving} loadingText="Saving..." disabled={!editValid}>
									Save
								</ActionButton>
							</div>
						{/if}
					</div>
					<div class="space-y-3">
						{#each strategic as row (row.block)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-[var(--netz-text-primary)]">{row.block}</span>
								<div class="flex items-center gap-2">
									{#if row.min_weight !== null && row.max_weight !== null}
										<span class="text-xs text-[var(--netz-text-muted)]">
											[{formatPercent(row.min_weight, 0, "en-US")}–{formatPercent(row.max_weight, 0, "en-US")}]
										</span>
									{/if}
									{#if editing}
										<input
											type="number"
											class="w-20 rounded border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-2 py-1 text-right text-sm font-medium text-[var(--netz-text-primary)]"
											bind:value={editWeights[row.block]}
											min={row.min_weight !== null ? row.min_weight * 100 : 0}
											max={row.max_weight !== null ? row.max_weight * 100 : 100}
											step="0.1"
										/>
									{:else}
										<span class="font-medium text-[var(--netz-text-primary)]">
											{formatPercent(row.weight, 1, "en-US")}
										</span>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
					<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Distribution</h3>
					<div class="h-64">
						<BarChart data={strategicChartData} orientation="horizontal" />
					</div>
				</div>
			</div>
		{:else}
			<EmptyState title="No Strategic Allocation" message="Strategic allocation has not been configured." />
		{/if}
	{/if}

	<!-- Tactical View -->
	{#if activeTab === "tactical"}
		{#if tactical.length > 0}
			<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
				<div class="mb-4 flex items-center justify-between">
					<h3 class="text-sm font-semibold text-[var(--netz-text-primary)]">Tactical Positions</h3>
					{#if !editingTactical}
						<Button size="sm" variant="outline" onclick={startEditingTactical}>Edit</Button>
					{:else}
						<div class="flex gap-2">
							<Button size="sm" variant="outline" onclick={() => editingTactical = false}>Cancel</Button>
							<ActionButton size="sm" onclick={saveTactical} loading={savingTactical} loadingText="Saving...">
								Save
							</ActionButton>
						</div>
					{/if}
				</div>
				<div class="space-y-3">
					{#each tactical as pos (pos.block)}
						<div class="flex items-center justify-between">
							<span class="text-sm text-[var(--netz-text-primary)]">{pos.block}</span>
							<div class="flex items-center gap-3">
								{#if pos.conviction !== null}
									<span class="text-xs text-[var(--netz-text-muted)]">
										Conviction: {formatNumber(pos.conviction, 0, "en-US")}
									</span>
								{/if}
								{#if editingTactical}
									<input
										type="number"
										class="w-20 rounded border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-2 py-1 text-right text-sm font-medium text-[var(--netz-text-primary)]"
										bind:value={editTactical[pos.block]}
										step="0.1"
									/>
								{:else}
									<span class="font-medium {pos.overweight >= 0 ? 'text-[var(--netz-success,#22c55e)]' : 'text-[var(--netz-danger,#ef4444)]'}">
										{formatPercent(pos.overweight, 1, "en-US", true)}
									</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<EmptyState title="No Tactical Positions" message="No active tactical overweights." />
		{/if}
	{/if}

	<!-- Effective View -->
	{#if activeTab === "effective"}
		{#if effective.length > 0}
			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
					<div class="mb-4 flex items-center justify-between">
						<h3 class="text-sm font-semibold text-[var(--netz-text-primary)]">Effective Allocation</h3>
						<span class="text-xs text-[var(--netz-text-muted)]">
							Total: {formatPercent(totalWeight, 1, "en-US")}
						</span>
					</div>
					<div class="space-y-3">
						{#each effective as row (row.block)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-[var(--netz-text-primary)]">{row.block}</span>
								<div class="flex items-center gap-2 text-xs">
									<span class="text-[var(--netz-text-muted)]">
										{formatPercent(row.strategic_weight, 1, "en-US")}
									</span>
									{#if row.tactical_overweight !== 0}
										<span class="{row.tactical_overweight >= 0 ? 'text-[var(--netz-success,#22c55e)]' : 'text-[var(--netz-danger,#ef4444)]'}">
											{formatPercent(row.tactical_overweight, 1, "en-US", true)}
										</span>
									{/if}
									<span class="font-medium text-[var(--netz-text-primary)]">
										= {formatPercent(row.effective_weight, 1, "en-US")}
									</span>
								</div>
							</div>
						{/each}
					</div>
				</div>
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
					<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Distribution</h3>
					<div class="h-64">
						<BarChart data={effectiveChartData} orientation="horizontal" />
					</div>
				</div>
			</div>
		{:else}
			<EmptyState title="No Allocation Data" message="Effective allocation will appear once strategic weights are set." />
		{/if}
	{/if}
</div>
