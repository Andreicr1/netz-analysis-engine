<!--
  Allocation — strategic, tactical, and effective views with profile selector.
-->
<script lang="ts">
	import { DataCard, BarChart, PageHeader, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";
	import { goto } from "$app/navigation";

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

	<!-- Strategic View -->
	{#if activeTab === "strategic"}
		{#if strategic.length > 0}
			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
					<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Strategic Weights</h3>
					<div class="space-y-3">
						{#each strategic as row (row.block)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-[var(--netz-text-primary)]">{row.block}</span>
								<div class="flex items-center gap-2">
									{#if row.min_weight !== null && row.max_weight !== null}
										<span class="text-xs text-[var(--netz-text-muted)]">
											[{(row.min_weight * 100).toFixed(0)}–{(row.max_weight * 100).toFixed(0)}%]
										</span>
									{/if}
									<span class="font-medium text-[var(--netz-text-primary)]">
										{(row.weight * 100).toFixed(1)}%
									</span>
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
				<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Tactical Positions</h3>
				<div class="space-y-3">
					{#each tactical as pos (pos.block)}
						<div class="flex items-center justify-between">
							<span class="text-sm text-[var(--netz-text-primary)]">{pos.block}</span>
							<div class="flex items-center gap-3">
								{#if pos.conviction !== null}
									<span class="text-xs text-[var(--netz-text-muted)]">
										Conviction: {pos.conviction.toFixed(0)}
									</span>
								{/if}
								<span class="font-medium {pos.overweight >= 0 ? 'text-[var(--netz-success,#22c55e)]' : 'text-[var(--netz-danger,#ef4444)]'}">
									{pos.overweight >= 0 ? "+" : ""}{(pos.overweight * 100).toFixed(1)}%
								</span>
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
							Total: {(totalWeight * 100).toFixed(1)}%
						</span>
					</div>
					<div class="space-y-3">
						{#each effective as row (row.block)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-[var(--netz-text-primary)]">{row.block}</span>
								<div class="flex items-center gap-2 text-xs">
									<span class="text-[var(--netz-text-muted)]">
										{(row.strategic_weight * 100).toFixed(1)}%
									</span>
									{#if row.tactical_overweight !== 0}
										<span class="{row.tactical_overweight >= 0 ? 'text-[var(--netz-success,#22c55e)]' : 'text-[var(--netz-danger,#ef4444)]'}">
											{row.tactical_overweight >= 0 ? "+" : ""}{(row.tactical_overweight * 100).toFixed(1)}%
										</span>
									{/if}
									<span class="font-medium text-[var(--netz-text-primary)]">
										= {(row.effective_weight * 100).toFixed(1)}%
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
