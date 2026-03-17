<!--
  Instruments Management — list, create, bulk sync, external search + import.
  Uses $state.raw for performance with 500+ items.
-->
<script lang="ts">
	import { DataTable, PageHeader, EmptyState, Button, Card, Dialog, ContextPanel } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	import type { Instrument } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let instruments = $state.raw((data.instruments ?? []) as Instrument[]);
	$effect(() => {
		instruments = (data.instruments ?? []) as Instrument[];
	});

	// ── Search filter ──
	let searchQuery = $state("");
	let filtered = $derived(
		searchQuery.trim()
			? instruments.filter(i =>
				i.ticker?.toLowerCase().includes(searchQuery.toLowerCase()) ||
				i.name?.toLowerCase().includes(searchQuery.toLowerCase())
			)
			: instruments
	);

	// ── Detail panel ──
	let selectedInstrument = $state<Instrument | null>(null);
	let panelOpen = $derived(selectedInstrument !== null);
	let loadingDetail = $state(false);
	let instrumentDetail = $state<Record<string, unknown> | null>(null);

	async function openDetail(instrument: Instrument) {
		selectedInstrument = instrument;
		loadingDetail = true;
		try {
			const api = createClientApiClient(getToken);
			instrumentDetail = await api.get(`/instruments/${instrument.id}`);
		} catch {
			instrumentDetail = null;
		} finally {
			loadingDetail = false;
		}
	}

	// ── Create Instrument Dialog ──
	let showCreate = $state(false);
	let saving = $state(false);
	let createError = $state<string | null>(null);
	let createForm = $state({
		ticker: "",
		name: "",
		asset_class: "equity",
		currency: "USD",
	});

	function resetCreateForm() {
		createForm = { ticker: "", name: "", asset_class: "equity", currency: "USD" };
		createError = null;
	}

	async function createInstrument() {
		saving = true;
		createError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/instruments", {
				ticker: createForm.ticker.trim().toUpperCase(),
				name: createForm.name.trim(),
				asset_class: createForm.asset_class,
				currency: createForm.currency,
			});
			showCreate = false;
			resetCreateForm();
			await invalidateAll();
		} catch (e) {
			createError = e instanceof Error ? e.message : "Failed to create instrument";
		} finally {
			saving = false;
		}
	}

	// ── Bulk Sync ──
	let showBulkSync = $state(false);
	let syncing = $state(false);

	async function bulkSync() {
		syncing = true;
		showBulkSync = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/instruments/bulk-sync", {});
			await invalidateAll();
		} catch (e) {
			createError = e instanceof Error ? e.message : "Bulk sync failed";
		} finally {
			syncing = false;
		}
	}

	// ── External Search ──
	let showExternalSearch = $state(false);
	let externalQuery = $state("");
	let searching = $state(false);
	let externalResults = $state<Array<Record<string, unknown>>>([]);
	let importingId = $state<string | null>(null);

	async function searchExternal() {
		if (!externalQuery.trim()) return;
		searching = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ results: Array<Record<string, unknown>> }>("/instruments/search-external", {
				query: externalQuery.trim(),
			}, { timeoutMs: 10_000 });
			externalResults = res.results ?? [];
		} catch (e) {
			externalResults = [];
			createError = e instanceof Error ? e.message : "External search failed";
		} finally {
			searching = false;
		}
	}

	async function importInstrument(ext: Record<string, unknown>) {
		const id = String(ext.id ?? ext.ticker ?? "");
		importingId = id;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/instruments", {
				ticker: String(ext.ticker ?? "").toUpperCase(),
				name: String(ext.name ?? ""),
				asset_class: String(ext.asset_class ?? "equity"),
				currency: String(ext.currency ?? "USD"),
			});
			await invalidateAll();
		} catch (e) {
			createError = e instanceof Error ? e.message : "Import failed";
		} finally {
			importingId = null;
		}
	}

	const columns = [
		{ accessorKey: "ticker", header: "Ticker" },
		{ accessorKey: "name", header: "Name" },
		{ accessorKey: "asset_class", header: "Asset Class" },
		{ accessorKey: "currency", header: "Currency" },
		{ accessorKey: "last_price", header: "Last Price" },
		{ accessorKey: "exchange", header: "Exchange" },
	];
</script>

<div class="flex h-full">
	<div class="flex-1 space-y-4 p-6">
		<PageHeader title="Instruments ({instruments.length})">
			{#snippet actions()}
				<div class="flex gap-2">
					<Button onclick={() => { resetCreateForm(); showCreate = true; }}>Add Instrument</Button>
					<Button variant="outline" onclick={() => showBulkSync = true} disabled={syncing}>
						{syncing ? "Syncing..." : "Bulk Sync"}
					</Button>
					<Button variant="outline" onclick={() => { externalResults = []; showExternalSearch = true; }}>
						Search External
					</Button>
				</div>
			{/snippet}
		</PageHeader>

		<!-- Search filter -->
		<input
			type="text"
			bind:value={searchQuery}
			placeholder="Filter by ticker or name..."
			class="w-full max-w-sm rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
		/>

		{#if filtered.length === 0}
			<EmptyState
				title="No Instruments"
				description={searchQuery ? "No instruments match your filter." : "Add instruments to get started."}
			/>
		{:else}
			<DataTable
				data={filtered}
				{columns}
				onRowClick={(row) => openDetail(row as unknown as Instrument)}
			/>
		{/if}
	</div>

	<!-- Detail Panel -->
	{#if selectedInstrument}
		<ContextPanel
			open={panelOpen}
			title={selectedInstrument.ticker ?? "Instrument"}
			onClose={() => { selectedInstrument = null; instrumentDetail = null; }}
		>
			<div class="space-y-4 p-4">
				{#if loadingDetail}
					<p class="text-sm text-[var(--netz-text-muted)]">Loading...</p>
				{:else if instrumentDetail}
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Name</p>
						<p class="text-sm font-medium">{instrumentDetail.name ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Asset Class</p>
						<p class="text-sm">{instrumentDetail.asset_class ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Currency</p>
						<p class="text-sm">{instrumentDetail.currency ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Last Price</p>
						<p class="text-sm">{instrumentDetail.last_price ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Exchange</p>
						<p class="text-sm">{instrumentDetail.exchange ?? "—"}</p>
					</div>
				{:else}
					<p class="text-sm text-[var(--netz-text-muted)]">Details unavailable.</p>
				{/if}
			</div>
		</ContextPanel>
	{/if}
</div>

<!-- Create Instrument Dialog -->
<Dialog bind:open={showCreate} title="Add Instrument">
	<form onsubmit={(e) => { e.preventDefault(); createInstrument(); }} class="space-y-4">
		<FormField label="Ticker" required>
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)] uppercase"
				bind:value={createForm.ticker}
				placeholder="e.g. AAPL"
			/>
		</FormField>
		<FormField label="Name" required>
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={createForm.name}
				placeholder="e.g. Apple Inc."
			/>
		</FormField>
		<FormField label="Asset Class">
			<select
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={createForm.asset_class}
			>
				<option value="equity">Equity</option>
				<option value="fixed_income">Fixed Income</option>
				<option value="commodity">Commodity</option>
				<option value="fx">FX</option>
				<option value="alternative">Alternative</option>
			</select>
		</FormField>
		<FormField label="Currency">
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)] uppercase"
				bind:value={createForm.currency}
				placeholder="USD"
			/>
		</FormField>
		{#if createError}
			<p class="text-sm text-[var(--netz-status-error)]">{createError}</p>
		{/if}
		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreate = false}>Cancel</Button>
			<ActionButton onclick={createInstrument} loading={saving} loadingText="Creating..." disabled={!createForm.ticker.trim() || !createForm.name.trim()}>
				Create
			</ActionButton>
		</div>
	</form>
</Dialog>

<!-- Bulk Sync Confirmation -->
<ConfirmDialog
	bind:open={showBulkSync}
	title="Bulk Sync Instruments"
	message="This will sync instrument data from external providers. Existing instruments will be updated. Continue?"
	confirmLabel="Sync"
	confirmVariant="default"
	onConfirm={bulkSync}
	onCancel={() => showBulkSync = false}
/>

<!-- External Search Dialog -->
<Dialog bind:open={showExternalSearch} title="Search External Providers">
	<div class="space-y-4">
		<div class="flex gap-2">
			<input
				type="text"
				bind:value={externalQuery}
				placeholder="Search by ticker or name..."
				class="flex-1 rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				onkeydown={(e) => { if (e.key === "Enter") searchExternal(); }}
			/>
			<ActionButton onclick={searchExternal} loading={searching} loadingText="Searching...">
				Search
			</ActionButton>
		</div>

		{#if externalResults.length > 0}
			<div class="max-h-64 space-y-2 overflow-y-auto">
				{#each externalResults as result}
					<Card class="flex items-center justify-between p-3">
						<div>
							<p class="text-sm font-medium text-[var(--netz-text-primary)]">
								{result.ticker ?? "—"} — {result.name ?? "—"}
							</p>
							<p class="text-xs text-[var(--netz-text-muted)]">
								{result.asset_class ?? ""} | {result.currency ?? ""} | {result.exchange ?? ""}
							</p>
						</div>
						<ActionButton
							size="sm"
							onclick={() => importInstrument(result)}
							loading={importingId === String(result.id ?? result.ticker)}
							loadingText="..."
						>
							Import
						</ActionButton>
					</Card>
				{/each}
			</div>
		{:else if externalQuery && !searching}
			<p class="text-sm text-[var(--netz-text-muted)]">No results found.</p>
		{/if}
	</div>
</Dialog>
