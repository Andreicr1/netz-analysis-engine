<!--
  BlendedBenchmarkEditor — compose custom benchmarks from allocation blocks.
  Typeahead search, weight validation (must sum to 100%), normalize button,
  ConsequenceDialog on save, NAV chart after save.
-->
<script lang="ts">
	import {
		ActionButton, ConsequenceDialog, EmptyState,
		MetricCard, SectionCard,
		formatPercent, formatNumber,
	} from "@investintell/ui";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Input } from "@investintell/ui/components/ui/input";
	import { ChartContainer } from "@investintell/ui/charts";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		profile: string;
		onSaved?: () => void;
	}

	let { profile, onSaved }: Props = $props();

	// ── Types ──
	type Block = {
		block_id: string;
		display_name: string;
		benchmark_ticker: string | null;
		geography: string;
		asset_class: string;
	};

	type Component = {
		block_id: string;
		display_name: string;
		benchmark_ticker: string | null;
		weight: number; // 0-1 range
	};

	type BenchmarkData = {
		id: string;
		portfolio_profile: string;
		name: string;
		is_active: boolean;
		components: Array<{
			id: string;
			block_id: string;
			weight: number;
			display_name: string | null;
			benchmark_ticker: string | null;
		}>;
	};

	type NavPoint = { date: string; nav: number; return_1d: number };

	// ── State ──
	let availableBlocks = $state<Block[]>([]);
	let currentBenchmark = $state<BenchmarkData | null>(null);
	let components = $state<Component[]>([]);
	let benchmarkName = $state("");
	let searchQuery = $state("");
	let navSeries = $state<NavPoint[]>([]);
	let loading = $state(true);
	let saving = $state(false);
	let loadingNav = $state(false);
	let error = $state<string | null>(null);
	let showConfirmDialog = $state(false);

	// ── Derived ──
	let totalWeight = $derived(
		components.reduce((sum, c) => sum + c.weight, 0)
	);
	let isValidWeight = $derived(Math.abs(totalWeight - 1.0) < 0.0001);
	let hasChanges = $derived(components.length > 0);

	let filteredBlocks = $derived.by(() => {
		const q = searchQuery.toLowerCase().trim();
		if (!q) return availableBlocks;
		return availableBlocks.filter((b) =>
			b.display_name.toLowerCase().includes(q) ||
			b.geography.toLowerCase().includes(q) ||
			b.asset_class.toLowerCase().includes(q) ||
			(b.benchmark_ticker?.toLowerCase().includes(q) ?? false)
		);
	});

	// Exclude already-selected blocks
	let selectableBlocks = $derived(
		filteredBlocks.filter((b) => !components.some((c) => c.block_id === b.block_id))
	);

	// ── NAV Chart ──
	let navChartOption = $derived.by(() => {
		if (navSeries.length === 0) return null;
		return {
			tooltip: {
				trigger: "axis" as const,
				formatter: (params: Array<{ name: string; value: number }>) => {
					const p = params[0];
					if (!p) return "";
					return `${p.name}: ${formatNumber(p.value, 2, "en-US")}`;
				},
			},
			grid: { left: 60, right: 20, top: 20, bottom: 40 },
			xAxis: {
				type: "category" as const,
				data: navSeries.map((p) => p.date),
				axisLabel: { fontSize: 10, rotate: 30 },
			},
			yAxis: {
				type: "value" as const,
				axisLabel: { formatter: (v: number) => formatNumber(v, 1, "en-US") },
			},
			series: [
				{
					type: "line" as const,
					data: navSeries.map((p) => p.nav),
					smooth: true,
					showSymbol: false,
					areaStyle: { opacity: 0.1 },
				},
			],
		};
	});

	// ── Load on mount ──
	async function loadData() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const [blocks, benchmark] = await Promise.allSettled([
				api.get<Block[]>("/blended-benchmarks/blocks"),
				api.get<BenchmarkData | null>(`/blended-benchmarks/${profile}`),
			]);

			availableBlocks = blocks.status === "fulfilled" ? blocks.value : [];
			currentBenchmark = benchmark.status === "fulfilled" ? benchmark.value : null;

			if (currentBenchmark?.components) {
				benchmarkName = currentBenchmark.name;
				components = currentBenchmark.components.map((c) => ({
					block_id: c.block_id,
					display_name: c.display_name ?? c.block_id,
					benchmark_ticker: c.benchmark_ticker ?? null,
					weight: Number(c.weight),
				}));
				// Load NAV series
				await loadNavSeries(currentBenchmark.id);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load data";
		} finally {
			loading = false;
		}
	}

	async function loadNavSeries(benchmarkId: string) {
		loadingNav = true;
		try {
			const api = createClientApiClient(getToken);
			navSeries = await api.get<NavPoint[]>(`/blended-benchmarks/${benchmarkId}/nav`);
		} catch {
			navSeries = [];
		} finally {
			loadingNav = false;
		}
	}

	// ── Delete benchmark ──
	let showDeleteDialog = $state(false);
	let deleting = $state(false);

	async function handleDelete(payload: ConsequenceDialogPayload) {
		if (!currentBenchmark) return;
		deleting = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.delete(`/blended-benchmarks/${currentBenchmark.id}`);
			showDeleteDialog = false;
			currentBenchmark = null;
			components = [];
			benchmarkName = "";
			navSeries = [];
			onSaved?.();
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to delete benchmark";
		} finally {
			deleting = false;
		}
	}

	$effect(() => { void loadData(); });

	// ── Actions ──
	function addBlock(block: Block) {
		const newCount = components.length + 1;
		const equalWeight = 1.0 / newCount;

		// Normalize existing weights proportionally
		const currentTotal = components.reduce((s, c) => s + c.weight, 0);
		const scaleFactor = currentTotal > 0 ? (1.0 - equalWeight) / currentTotal : 0;

		components = [
			...components.map((c) => ({ ...c, weight: c.weight * scaleFactor })),
			{
				block_id: block.block_id,
				display_name: block.display_name,
				benchmark_ticker: block.benchmark_ticker,
				weight: equalWeight,
			},
		];
		searchQuery = "";
	}

	function removeBlock(blockId: string) {
		components = components.filter((c) => c.block_id !== blockId);
		if (components.length > 0) {
			normalizeWeights();
		}
	}

	function normalizeWeights() {
		const total = components.reduce((s, c) => s + c.weight, 0);
		if (total <= 0) return;
		components = components.map((c) => ({
			...c,
			weight: c.weight / total,
		}));
	}

	function requestSave() {
		if (!isValidWeight || !benchmarkName.trim()) return;
		showConfirmDialog = true;
	}

	async function handleSave(payload: ConsequenceDialogPayload) {
		saving = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<BenchmarkData>(`/blended-benchmarks/${profile}`, {
				name: benchmarkName.trim(),
				components: components.map((c) => ({
					block_id: c.block_id,
					weight: Math.round(c.weight * 10000) / 10000,
				})),
			});
			currentBenchmark = result;
			showConfirmDialog = false;
			if (result?.id) {
				await loadNavSeries(result.id);
			}
			onSaved?.();
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to save benchmark";
		} finally {
			saving = false;
		}
	}
</script>

<div class="space-y-4">
	{#if loading}
		<p class="text-sm text-(--ii-text-muted)">Loading benchmark data...</p>
	{:else}
		{#if error}
			<div class="rounded-md border border-(--ii-status-error) bg-(--ii-status-error)/10 p-3 text-sm text-(--ii-status-error)">
				{error}
				<button class="ml-2 underline" onclick={() => error = null}>dismiss</button>
			</div>
		{/if}

		<!-- Benchmark Name -->
		<div class="flex items-end gap-3">
			<div class="flex-1">
				<label class="mb-1 block text-xs font-medium text-(--ii-text-muted)" for="benchmark-name-input">Benchmark Name</label>
				<Input
					id="benchmark-name-input"
					bind:value={benchmarkName}
					placeholder="e.g. 60/40 Blend, Moderate Custom"
				/>
			</div>
		</div>

		<!-- Components Table -->
		{#if components.length > 0}
			<SectionCard title="Components" subtitle="Weight allocation per block">
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-(--ii-border) text-left text-xs font-medium uppercase tracking-wider text-(--ii-text-secondary)">
								<th class="pb-2 pr-4">Block</th>
								<th class="pb-2 pr-4">Ticker</th>
								<th class="pb-2 pr-4 text-right">Weight</th>
								<th class="pb-2 pr-4 text-right">%</th>
								<th class="pb-2"></th>
							</tr>
						</thead>
						<tbody>
							{#each components as comp, i (comp.block_id)}
								<tr class="border-b border-(--ii-border)/50">
									<td class="py-2 pr-4 text-(--ii-text-primary)">{comp.display_name}</td>
									<td class="py-2 pr-4 font-mono text-xs text-(--ii-text-muted)">{comp.benchmark_ticker ?? "—"}</td>
									<td class="py-2 pr-4 text-right">
										<input
											type="number"
											class="w-20 rounded border border-(--ii-border) bg-(--ii-surface-elevated) px-2 py-1 text-right font-mono text-sm text-(--ii-text-primary)"
											min="0.01"
											max="1"
											step="0.01"
											value={formatNumber(components[i]!.weight, 4)}
											oninput={(e) => {
												const val = parseFloat((e.target as HTMLInputElement).value);
												if (!isNaN(val) && val > 0 && val <= 1) {
													components[i]!.weight = val;
													components = [...components];
												}
											}}
										/>
									</td>
									<td class="py-2 pr-4 text-right font-mono text-xs text-(--ii-text-secondary)">
										{formatPercent(comp.weight, 1, "en-US")}
									</td>
									<td class="py-2 text-right">
										<button
											class="text-xs text-(--ii-danger) hover:underline"
											onclick={() => removeBlock(comp.block_id)}
										>
											Remove
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- Weight Total Bar -->
				<div class="mt-3 flex items-center justify-between">
					<div class="flex items-center gap-3">
						<span class="text-sm font-semibold {isValidWeight ? 'text-(--ii-success)' : 'text-(--ii-danger)'}">
							Total: {formatPercent(totalWeight, 2, "en-US")}
							{#if isValidWeight}
								&#10003;
							{:else}
								(must equal 100%)
							{/if}
						</span>
						<Button size="sm" variant="outline" onclick={normalizeWeights}>
							Normalize
						</Button>
					</div>
					{#if currentBenchmark}
						<Button size="sm" variant="destructive" onclick={() => showDeleteDialog = true} disabled={deleting}>
							{deleting ? "Deleting…" : "Delete"}
						</Button>
					{/if}
					<ActionButton
						size="sm"
						onclick={requestSave}
						loading={saving}
						loadingText="Saving..."
						disabled={!isValidWeight || !benchmarkName.trim() || components.length === 0}
					>
						Save Benchmark
					</ActionButton>
				</div>
			</SectionCard>
		{/if}

		<!-- Search + Add Blocks -->
		<SectionCard title="Add Blocks" subtitle="Search allocation blocks to add as benchmark components">
			<div class="mb-3">
				<Input
					bind:value={searchQuery}
					placeholder="Search by name, geography, asset class, or ticker..."
				/>
			</div>
			{#if selectableBlocks.length > 0}
				<div class="max-h-60 space-y-1 overflow-y-auto">
					{#each selectableBlocks as block (block.block_id)}
						<button
							class="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-(--ii-surface-alt)"
							onclick={() => addBlock(block)}
						>
							<div>
								<span class="font-medium text-(--ii-text-primary)">{block.display_name}</span>
								<span class="ml-2 text-xs text-(--ii-text-muted)">
									{block.geography} / {block.asset_class}
								</span>
							</div>
							<span class="font-mono text-xs text-(--ii-text-muted)">
								{block.benchmark_ticker ?? "—"}
							</span>
						</button>
					{/each}
				</div>
			{:else if searchQuery.trim()}
				<p class="text-sm text-(--ii-text-muted)">No matching blocks found.</p>
			{:else if availableBlocks.length === 0}
				<EmptyState title="No Blocks Available" message="No allocation blocks with benchmark tickers are configured." />
			{:else}
				<p class="text-sm text-(--ii-text-muted)">All available blocks already added.</p>
			{/if}
		</SectionCard>

		<!-- NAV Chart -->
		{#if navSeries.length > 0}
			<SectionCard title="Blended NAV Series" subtitle="Indexed to 100 from weighted constituent returns">
				<div class="grid gap-4 sm:grid-cols-3 mb-4">
					<MetricCard
						label="Latest NAV"
						value={formatNumber(navSeries[navSeries.length - 1]!.nav, 2, "en-US")}
						sublabel="Base 100"
					/>
					<MetricCard
						label="Data Points"
						value={String(navSeries.length)}
						sublabel="Trading days"
					/>
					<MetricCard
						label="Components"
						value={String(components.length)}
						sublabel="Weighted blocks"
					/>
				</div>
				{#if navChartOption}
					<ChartContainer
						option={navChartOption}
						height={320}
						ariaLabel="{profile} blended benchmark NAV"
					/>
				{/if}
			</SectionCard>
		{:else if loadingNav}
			<p class="text-sm text-(--ii-text-muted)">Loading NAV series...</p>
		{/if}
	{/if}
</div>

<!-- Save ConsequenceDialog -->
<ConsequenceDialog
	bind:open={showConfirmDialog}
	title="Save Blended Benchmark"
	impactSummary="This will create a new blended benchmark for the {profile} profile. Any previous benchmark for this profile will be deactivated."
	requireRationale={true}
	rationaleLabel="Benchmark rationale"
	rationalePlaceholder="Describe the investment thesis for this benchmark composition (min 10 chars)."
	rationaleMinLength={10}
	confirmLabel="Save Benchmark"
	metadata={[
		{ label: "Profile", value: profile },
		{ label: "Name", value: benchmarkName },
		{ label: "Components", value: String(components.length) },
		{ label: "Total Weight", value: formatPercent(totalWeight, 2, "en-US"), emphasis: !isValidWeight },
	]}
	onConfirm={handleSave}
	onCancel={() => { showConfirmDialog = false; }}
/>

<ConsequenceDialog
	bind:open={showDeleteDialog}
	title="Delete Blended Benchmark"
	impactSummary="This will permanently delete the blended benchmark for the {profile} profile. NAV history will be lost."
	destructive={true}
	requireRationale={true}
	rationaleLabel="Deletion rationale"
	rationalePlaceholder="Explain why this benchmark should be removed (min 10 chars)."
	rationaleMinLength={10}
	confirmLabel="Delete Benchmark"
	metadata={[
		{ label: "Profile", value: profile },
		{ label: "Name", value: currentBenchmark?.name ?? "—" },
	]}
	onConfirm={handleDelete}
	onCancel={() => { showDeleteDialog = false; }}
/>
