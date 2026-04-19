<!--
  InstrumentsView — Instruments CRUD + Yahoo/CSV import.
  Self-loading component for embedding in Screener tabs.
-->
<script lang="ts">
	import { DataTable, EmptyState, ContextPanel, ActionButton, ConfirmDialog, FormField, Toast } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Checkbox } from "@investintell/ui/components/ui/checkbox";
	import { Label } from "@investintell/ui/components/ui/label";
	import { Skeleton } from "@investintell/ui/components/ui/skeleton";
	import { Dialog, Input, Select, Textarea } from "@investintell/ui";
	import { createClientApiClient } from "$wealth/api/client";
	import { getContext } from "svelte";
	import type { Instrument } from "$wealth/types/api";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let instruments = $state<Instrument[]>([]);
	let loading = $state(true);

	async function fetchData() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.get("/instruments", { limit: 500 });
			instruments = (result ?? []) as Instrument[];
		} catch {
			instruments = [];
		} finally {
			loading = false;
		}
	}

	// Search filter
	let searchQuery = $state("");
	let filtered = $derived(
		searchQuery.trim()
			? instruments.filter(i =>
				i.ticker?.toLowerCase().includes(searchQuery.toLowerCase()) ||
				i.name?.toLowerCase().includes(searchQuery.toLowerCase())
			)
			: instruments
	);

	// Detail panel
	let selectedInstrument = $state<Instrument | null>(null);
	let panelOpen = $derived(selectedInstrument !== null);
	let loadingDetail = $state(false);
	let instrumentDetail = $state<Record<string, unknown> | null>(null);

	// Edit mode
	let editing = $state(false);
	let editSaving = $state(false);
	let editError = $state<string | null>(null);
	let editForm = $state({ name: "", block_id: "", asset_class: "", geography: "", currency: "", is_active: true });

	function startEditing() {
		if (!instrumentDetail) return;
		editForm = {
			name: (instrumentDetail.name as string) ?? "",
			block_id: (instrumentDetail.block_id as string) ?? "",
			asset_class: (instrumentDetail.asset_class as string) ?? "",
			geography: (instrumentDetail.geography as string) ?? "",
			currency: (instrumentDetail.currency as string) ?? "",
			is_active: (instrumentDetail.is_active as boolean) ?? true,
		};
		editError = null;
		editing = true;
	}

	function cancelEditing() {
		editing = false;
		editError = null;
	}

	async function saveEdit() {
		if (!selectedInstrument || !instrumentDetail) return;
		editSaving = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const body: Record<string, unknown> = {};
			if (editForm.name !== (instrumentDetail.name ?? "")) body.name = editForm.name;
			if (editForm.block_id !== (instrumentDetail.block_id ?? "")) body.block_id = editForm.block_id || null;
			if (editForm.asset_class !== (instrumentDetail.asset_class ?? "")) body.asset_class = editForm.asset_class;
			if (editForm.geography !== (instrumentDetail.geography ?? "")) body.geography = editForm.geography;
			if (editForm.currency !== (instrumentDetail.currency ?? "")) body.currency = editForm.currency;
			if (editForm.is_active !== (instrumentDetail.is_active ?? true)) body.is_active = editForm.is_active;
			if (Object.keys(body).length === 0) {
				editing = false;
				return;
			}
			const id = (instrumentDetail.instrument_id as string) ?? selectedInstrument.id;
			const updated = await api.patch<Record<string, unknown>>(`/instruments/${id}`, body);
			instrumentDetail = updated;
			editing = false;
			toast = { message: "Instrument updated", type: "success" };
			await fetchData();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to update instrument";
		} finally {
			editSaving = false;
		}
	}

	async function openDetail(instrument: Instrument) {
		selectedInstrument = instrument;
		editing = false;
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

	// Create Instrument Dialog
	let showCreate = $state(false);
	let saving = $state(false);
	let createError = $state<string | null>(null);
	let createForm = $state({ ticker: "", name: "", asset_class: "equity", currency: "USD" });

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
			await fetchData();
		} catch (e) {
			createError = e instanceof Error ? e.message : "Failed to create instrument";
		} finally {
			saving = false;
		}
	}

	// Bulk Sync
	let showBulkSync = $state(false);
	let syncing = $state(false);

	async function bulkSync() {
		syncing = true;
		showBulkSync = false;
		try {
			const api = createClientApiClient(getToken);
			const tickers = instruments.filter(i => i.ticker).map(i => i.ticker);
			if (tickers.length === 0) {
				toast = { message: "No instruments with tickers to sync", type: "warning" };
				return;
			}
			await api.post("/instruments/import/yahoo", { tickers });
			toast = { message: `${tickers.length} instruments refreshed from Yahoo Finance`, type: "success" };
			await fetchData();
		} catch (e) {
			toast = { message: e instanceof Error ? e.message : "Bulk sync failed", type: "error" };
		} finally {
			syncing = false;
		}
	}

	// Import from Yahoo Finance
	let showImportYahoo = $state(false);
	let importTickers = $state("");
	let importing = $state(false);
	let importError = $state<string | null>(null);
	let parsedTickers = $derived(
		importTickers.split(/[,\n\s]+/).map(t => t.trim().toUpperCase()).filter(t => t.length > 0)
	);

	async function importFromYahoo() {
		if (parsedTickers.length === 0 || parsedTickers.length > 50) {
			importError = "Enter between 1 and 50 tickers";
			return;
		}
		importing = true;
		importError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/instruments/import/yahoo", { tickers: parsedTickers });
			showImportYahoo = false;
			importTickers = "";
			toast = { message: `${parsedTickers.length} instruments imported from Yahoo Finance`, type: "success" };
			await fetchData();
		} catch (e) {
			importError = e instanceof Error ? e.message : "Import failed";
		} finally {
			importing = false;
		}
	}

	// Import from CSV
	let showImportCsv = $state(false);
	let csvFile = $state<File | null>(null);
	let csvInstrumentType = $state("fund");
	let csvPreview = $state<string[][] | null>(null);
	let importingCsv = $state(false);
	let csvError = $state<string | null>(null);

	function handleCsvSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		csvFile = file;
		csvError = null;
		const reader = new FileReader();
		reader.onload = () => {
			const text = reader.result as string;
			const lines = text.split(/\r?\n/).filter(l => l.trim());
			csvPreview = lines.slice(0, 6).map(l => l.split(",").map(c => c.trim().replace(/^"|"$/g, "")));
		};
		reader.readAsText(file);
	}

	function resetCsvForm() {
		csvFile = null;
		csvPreview = null;
		csvError = null;
		csvInstrumentType = "fund";
	}

	async function importFromCsv() {
		if (!csvFile) return;
		importingCsv = true;
		csvError = null;
		try {
			const api = createClientApiClient(getToken);
			const formData = new FormData();
			formData.append("file", csvFile);
			const result = await api.upload<{ imported: number; skipped: number; errors: Array<Record<string, unknown>> }>(
				`/instruments/import/csv?instrument_type=${encodeURIComponent(csvInstrumentType)}`,
				formData,
			);
			showImportCsv = false;
			const parts = [];
			if (result.imported > 0) parts.push(`${result.imported} imported`);
			if (result.skipped > 0) parts.push(`${result.skipped} skipped`);
			if (result.errors.length > 0) parts.push(`${result.errors.length} errors`);
			toast = { message: `CSV import: ${parts.join(", ")}`, type: result.errors.length > 0 ? "warning" : "success" };
			resetCsvForm();
			await fetchData();
		} catch (e) {
			csvError = e instanceof Error ? e.message : "CSV import failed";
		} finally {
			importingCsv = false;
		}
	}

	// Toast
	let toast = $state<{ message: string; type: "success" | "error" | "warning" | "info" } | null>(null);

	const columns = [
		{ accessorKey: "ticker", header: "Ticker" },
		{ accessorKey: "name", header: "Name" },
		{ accessorKey: "asset_class", header: "Asset Class" },
		{ accessorKey: "currency", header: "Currency" },
		{ accessorKey: "last_price", header: "Last Price" },
		{ accessorKey: "exchange", header: "Exchange" },
	];

	// Load on mount
	fetchData();
</script>

<div class="space-y-4">
	{#if loading}
		<Skeleton class="h-10 max-w-sm rounded-lg" />
		<Skeleton class="h-64 rounded-xl" />
	{:else}
		<div class="flex items-center justify-between">
			<h3 class="text-sm font-semibold text-(--ii-text-primary)">Instruments ({instruments.length})</h3>
			<div class="flex gap-2">
				<Button onclick={() => { resetCreateForm(); showCreate = true; }}>Add Manual</Button>
				<Button variant="outline" onclick={() => { importTickers = ""; importError = null; showImportYahoo = true; }}>Import from Yahoo</Button>
				<Button variant="outline" onclick={() => { resetCsvForm(); showImportCsv = true; }}>Import CSV</Button>
				<Button variant="outline" onclick={() => showBulkSync = true} disabled={syncing}>
					{syncing ? "Syncing..." : "Refresh from Yahoo"}
				</Button>
			</div>
		</div>

		<Input type="text" bind:value={searchQuery} placeholder="Filter by ticker or name..." class="max-w-sm" />

		{#if filtered.length === 0}
			<EmptyState title="No Instruments" description={searchQuery ? "No instruments match your filter." : "Add instruments to get started."} />
		{:else}
			<DataTable data={filtered} {columns} onRowClick={(row) => openDetail(row as unknown as Instrument)} />
		{/if}
	{/if}
</div>

<!-- Detail Panel -->
{#if selectedInstrument}
	<ContextPanel open={panelOpen} title={selectedInstrument.ticker ?? "Instrument"} onClose={() => { selectedInstrument = null; instrumentDetail = null; editing = false; }}>
		<div class="space-y-4 p-4">
			{#if loadingDetail}
				<p class="text-sm text-(--ii-text-muted)">Loading...</p>
			{:else if instrumentDetail && editing}
				<form onsubmit={(e) => { e.preventDefault(); saveEdit(); }} class="space-y-3">
					<FormField label="Name">
						<Input type="text" bind:value={editForm.name} />
					</FormField>
					<FormField label="Asset Class">
						<Select bind:value={editForm.asset_class} options={[
							{ value: "equity", label: "Equity" },
							{ value: "fixed_income", label: "Fixed Income" },
							{ value: "commodity", label: "Commodity" },
							{ value: "fx", label: "FX" },
							{ value: "alternative", label: "Alternative" },
							{ value: "fund", label: "Fund" },
						]} />
					</FormField>
					<FormField label="Geography">
						<Input type="text" bind:value={editForm.geography} placeholder="e.g. US, Global, EM" />
					</FormField>
					<FormField label="Currency">
						<Input type="text" class="uppercase" bind:value={editForm.currency} placeholder="USD" />
					</FormField>
					<FormField label="Block ID">
						<Input type="text" bind:value={editForm.block_id} placeholder="Allocation block" />
					</FormField>
					<div class="flex items-center gap-2">
						<Checkbox id="edit-is-active" checked={editForm.is_active} onCheckedChange={(v) => { editForm.is_active = !!v; }} />
						<Label for="edit-is-active" class="text-sm text-(--ii-text-primary)">Active</Label>
					</div>
					{#if editError}<p class="text-sm text-(--ii-status-error)">{editError}</p>{/if}
					<div class="flex justify-end gap-2 pt-2">
						<Button variant="outline" onclick={cancelEditing}>Cancel</Button>
						<ActionButton onclick={saveEdit} loading={editSaving} loadingText="Saving..." disabled={!editForm.name.trim()}>Save</ActionButton>
					</div>
				</form>
			{:else if instrumentDetail}
				<div class="flex justify-end">
					<Button variant="outline" onclick={startEditing}>Edit</Button>
				</div>
				<div><p class="text-xs text-(--ii-text-muted)">Name</p><p class="text-sm font-medium">{instrumentDetail.name ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Asset Class</p><p class="text-sm">{instrumentDetail.asset_class ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Geography</p><p class="text-sm">{instrumentDetail.geography ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Currency</p><p class="text-sm">{instrumentDetail.currency ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Block ID</p><p class="text-sm">{instrumentDetail.block_id ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Last Price</p><p class="text-sm">{instrumentDetail.last_price ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Exchange</p><p class="text-sm">{instrumentDetail.exchange ?? "—"}</p></div>
				<div><p class="text-xs text-(--ii-text-muted)">Status</p><p class="text-sm">{instrumentDetail.is_active ? "Active" : "Inactive"}</p></div>
			{:else}
				<p class="text-sm text-(--ii-text-muted)">Details unavailable.</p>
			{/if}
		</div>
	</ContextPanel>
{/if}

<!-- Create Instrument Dialog -->
<Dialog bind:open={showCreate} title="Add Instrument">
	<form onsubmit={(e) => { e.preventDefault(); createInstrument(); }} class="space-y-4">
		<FormField label="Ticker" required><Input type="text" class="uppercase" bind:value={createForm.ticker} placeholder="e.g. AAPL" /></FormField>
		<FormField label="Name" required><Input type="text" bind:value={createForm.name} placeholder="e.g. Apple Inc." /></FormField>
		<FormField label="Asset Class">
			<Select bind:value={createForm.asset_class} options={[
				{ value: "equity", label: "Equity" },
				{ value: "fixed_income", label: "Fixed Income" },
				{ value: "commodity", label: "Commodity" },
				{ value: "fx", label: "FX" },
				{ value: "alternative", label: "Alternative" },
			]} />
		</FormField>
		<FormField label="Currency"><Input type="text" class="uppercase" bind:value={createForm.currency} placeholder="USD" /></FormField>
		{#if createError}<p class="text-sm text-(--ii-status-error)">{createError}</p>{/if}
		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreate = false}>Cancel</Button>
			<ActionButton onclick={createInstrument} loading={saving} loadingText="Creating..." disabled={!createForm.ticker.trim() || !createForm.name.trim()}>Create</ActionButton>
		</div>
	</form>
</Dialog>

<ConfirmDialog bind:open={showBulkSync} title="Refresh Instrument Data" message="This will refresh metadata for all instruments with tickers from Yahoo Finance. Continue?" confirmLabel="Refresh" confirmVariant="default" onConfirm={bulkSync} onCancel={() => showBulkSync = false} />

<!-- Import from Yahoo Dialog -->
<Dialog bind:open={showImportYahoo} title="Import from Yahoo Finance">
	<div class="space-y-4">
		<FormField label="Tickers" required>
			<Textarea bind:value={importTickers} placeholder="SPY, AGG, GLD, VWO, ARKK" rows={4} />
		</FormField>
		<p class="text-xs text-(--ii-text-muted)">
			Enter up to 50 tickers, separated by commas, spaces, or newlines.
			{#if parsedTickers.length > 0}
				<span class="font-medium text-(--ii-text-primary)">{parsedTickers.length} ticker{parsedTickers.length !== 1 ? "s" : ""} detected</span>
			{/if}
		</p>
		{#if importError}<p class="text-sm text-(--ii-status-error)">{importError}</p>{/if}
		<div class="flex justify-end gap-2">
			<Button variant="outline" onclick={() => showImportYahoo = false}>Cancel</Button>
			<ActionButton onclick={importFromYahoo} loading={importing} loadingText="Importing..." disabled={parsedTickers.length === 0 || parsedTickers.length > 50}>Import</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Import from CSV Dialog -->
<Dialog bind:open={showImportCsv} title="Import from CSV">
	<div class="space-y-4">
		<FormField label="Instrument Type" required>
			<Select bind:value={csvInstrumentType} options={[{ value: "fund", label: "Fund" }, { value: "bond", label: "Bond" }, { value: "equity", label: "Equity" }]} />
		</FormField>
		<FormField label="CSV File" required>
			<input type="file" accept=".csv" onchange={handleCsvSelect} class="block w-full text-sm text-(--ii-text-primary) file:mr-4 file:rounded-md file:border-0 file:bg-(--ii-surface-highlight) file:px-4 file:py-2 file:text-sm file:font-medium file:text-(--ii-text-primary) hover:file:bg-(--ii-surface-hover)" />
		</FormField>
		<p class="text-xs text-(--ii-text-muted)">CSV must have columns: <code class="font-mono">ticker, name, asset_class, currency</code>. Optional: <code class="font-mono">isin, geography, block_id</code>. Max 5 MB.</p>
		{#if csvPreview && csvPreview.length > 0}
			<div class="overflow-x-auto rounded-md border border-(--ii-border)">
				<table class="w-full text-xs">
					<thead><tr class="bg-(--ii-surface-highlight)">{#each csvPreview[0] as header (header)}<th class="px-3 py-1.5 text-left font-medium text-(--ii-text-secondary)">{header}</th>{/each}</tr></thead>
					<tbody>{#each csvPreview.slice(1, 6) as row, i (i)}<tr class="{i % 2 === 0 ? '' : 'bg-(--ii-surface-highlight/50)'}">{#each row as cell (cell)}<td class="px-3 py-1 text-(--ii-text-primary)">{cell}</td>{/each}</tr>{/each}</tbody>
				</table>
			</div>
		{/if}
		{#if csvError}<p class="text-sm text-(--ii-status-error)">{csvError}</p>{/if}
		<div class="flex justify-end gap-2">
			<Button variant="outline" onclick={() => showImportCsv = false}>Cancel</Button>
			<ActionButton onclick={importFromCsv} loading={importingCsv} loadingText="Importing..." disabled={!csvFile}>Import</ActionButton>
		</div>
	</div>
</Dialog>

{#if toast}<Toast message={toast.message} type={toast.type} onDismiss={() => toast = null} />{/if}
