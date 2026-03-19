<!--
  Instruments Management — list, create, Yahoo import, CSV import.
  Uses $state.raw for performance with 500+ items.
-->
<script lang="ts">
	import { DataTable, PageHeader, EmptyState, Button, Card, Dialog, ContextPanel, Input, Select, Textarea } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField, Toast } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	import type { Instrument } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let instruments = $derived((data.instruments ?? []) as Instrument[]);

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

	// ── Bulk Sync (via Yahoo Finance import) ──
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
			await invalidateAll();
		} catch (e) {
			toast = { message: e instanceof Error ? e.message : "Bulk sync failed", type: "error" };
		} finally {
			syncing = false;
		}
	}

	// ── Import from Yahoo Finance ──
	let showImportYahoo = $state(false);
	let importTickers = $state("");
	let importing = $state(false);
	let importError = $state<string | null>(null);
	let parsedTickers = $derived(
		importTickers
			.split(/[,\n\s]+/)
			.map(t => t.trim().toUpperCase())
			.filter(t => t.length > 0)
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
			await invalidateAll();
		} catch (e) {
			importError = e instanceof Error ? e.message : "Import failed";
		} finally {
			importing = false;
		}
	}

	// ── Import from CSV ──
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

		// Parse preview (first 5 rows)
		const reader = new FileReader();
		reader.onload = () => {
			const text = reader.result as string;
			const lines = text.split(/\r?\n/).filter(l => l.trim());
			csvPreview = lines.slice(0, 6).map(l =>
				l.split(",").map(c => c.trim().replace(/^"|"$/g, ""))
			);
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
			await invalidateAll();
		} catch (e) {
			csvError = e instanceof Error ? e.message : "CSV import failed";
		} finally {
			importingCsv = false;
		}
	}

	// ── Toast ──
	let toast = $state<{ message: string; type: "success" | "error" | "warning" | "info" } | null>(null);

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
	<div class="flex-1 space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
		<PageHeader title="Instruments ({instruments.length})">
			{#snippet actions()}
				<div class="flex gap-2">
					<Button onclick={() => { resetCreateForm(); showCreate = true; }}>Add Manual</Button>
					<Button variant="outline" onclick={() => { importTickers = ""; importError = null; showImportYahoo = true; }}>
						Import from Yahoo
					</Button>
					<Button variant="outline" onclick={() => { resetCsvForm(); showImportCsv = true; }}>
						Import CSV
					</Button>
					<Button variant="outline" onclick={() => showBulkSync = true} disabled={syncing}>
						{syncing ? "Syncing..." : "Refresh from Yahoo"}
					</Button>
				</div>
			{/snippet}
		</PageHeader>

		<!-- Search filter -->
		<Input
			type="text"
			bind:value={searchQuery}
			placeholder="Filter by ticker or name..."
			class="max-w-sm"
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
					<p class="text-sm text-(--netz-text-muted)">Loading...</p>
				{:else if instrumentDetail}
					<div>
						<p class="text-xs text-(--netz-text-muted)">Name</p>
						<p class="text-sm font-medium">{instrumentDetail.name ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-(--netz-text-muted)">Asset Class</p>
						<p class="text-sm">{instrumentDetail.asset_class ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-(--netz-text-muted)">Currency</p>
						<p class="text-sm">{instrumentDetail.currency ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-(--netz-text-muted)">Last Price</p>
						<p class="text-sm">{instrumentDetail.last_price ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-(--netz-text-muted)">Exchange</p>
						<p class="text-sm">{instrumentDetail.exchange ?? "—"}</p>
					</div>
				{:else}
					<p class="text-sm text-(--netz-text-muted)">Details unavailable.</p>
				{/if}
			</div>
		</ContextPanel>
	{/if}
</div>

<!-- Create Instrument Dialog -->
<Dialog bind:open={showCreate} title="Add Instrument">
	<form onsubmit={(e) => { e.preventDefault(); createInstrument(); }} class="space-y-4">
		<FormField label="Ticker" required>
			<Input
				type="text"
				class="uppercase"
				bind:value={createForm.ticker}
				placeholder="e.g. AAPL"
			/>
		</FormField>
		<FormField label="Name" required>
			<Input
				type="text"
				bind:value={createForm.name}
				placeholder="e.g. Apple Inc."
			/>
		</FormField>
		<FormField label="Asset Class">
			<Select
				bind:value={createForm.asset_class}
				options={[
					{ value: "equity", label: "Equity" },
					{ value: "fixed_income", label: "Fixed Income" },
					{ value: "commodity", label: "Commodity" },
					{ value: "fx", label: "FX" },
					{ value: "alternative", label: "Alternative" },
				]}
			/>
		</FormField>
		<FormField label="Currency">
			<Input
				type="text"
				class="uppercase"
				bind:value={createForm.currency}
				placeholder="USD"
			/>
		</FormField>
		{#if createError}
			<p class="text-sm text-(--netz-status-error)">{createError}</p>
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
	title="Refresh Instrument Data"
	message="This will refresh metadata for all instruments with tickers from Yahoo Finance. Existing data will be updated. Continue?"
	confirmLabel="Refresh"
	confirmVariant="default"
	onConfirm={bulkSync}
	onCancel={() => showBulkSync = false}
/>

<!-- Import from Yahoo Finance Dialog -->
<Dialog bind:open={showImportYahoo} title="Import from Yahoo Finance">
	<div class="space-y-4">
		<FormField label="Tickers" required>
			<Textarea
				bind:value={importTickers}
				placeholder="SPY, AGG, GLD, VWO, ARKK"
				rows={4}
			/>
		</FormField>
		<p class="text-xs text-(--netz-text-muted)">
			Enter up to 50 tickers, separated by commas, spaces, or newlines.
			{#if parsedTickers.length > 0}
				<span class="font-medium text-(--netz-text-primary)">
					{parsedTickers.length} ticker{parsedTickers.length !== 1 ? "s" : ""} detected
				</span>
			{/if}
		</p>
		{#if importError}
			<p class="text-sm text-(--netz-status-error)">{importError}</p>
		{/if}
		<div class="flex justify-end gap-2">
			<Button variant="outline" onclick={() => showImportYahoo = false}>Cancel</Button>
			<ActionButton
				onclick={importFromYahoo}
				loading={importing}
				loadingText="Importing..."
				disabled={parsedTickers.length === 0 || parsedTickers.length > 50}
			>
				Import
			</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Import from CSV Dialog -->
<Dialog bind:open={showImportCsv} title="Import from CSV">
	<div class="space-y-4">
		<FormField label="Instrument Type" required>
			<Select
				bind:value={csvInstrumentType}
				options={[
					{ value: "fund", label: "Fund" },
					{ value: "bond", label: "Bond" },
					{ value: "equity", label: "Equity" },
				]}
			/>
		</FormField>
		<FormField label="CSV File" required>
			<input
				type="file"
				accept=".csv"
				onchange={handleCsvSelect}
				class="block w-full text-sm text-(--netz-text-primary) file:mr-4 file:rounded-md file:border-0 file:bg-(--netz-surface-highlight) file:px-4 file:py-2 file:text-sm file:font-medium file:text-(--netz-text-primary) hover:file:bg-(--netz-surface-hover)"
			/>
		</FormField>
		<p class="text-xs text-(--netz-text-muted)">
			CSV must have columns: <code class="font-mono">ticker, name, asset_class, currency</code>.
			Optional: <code class="font-mono">isin, geography, block_id</code>. Max 5 MB.
		</p>

		{#if csvPreview && csvPreview.length > 0}
			<div class="overflow-x-auto rounded-md border border-(--netz-border)">
				<table class="w-full text-xs">
					<thead>
						<tr class="bg-(--netz-surface-highlight)">
							{#each csvPreview[0] as header}
								<th class="px-3 py-1.5 text-left font-medium text-(--netz-text-secondary)">{header}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each csvPreview.slice(1, 6) as row, i}
							<tr class="{i % 2 === 0 ? '' : 'bg-(--netz-surface-highlight/50)'}">
								{#each row as cell}
									<td class="px-3 py-1 text-(--netz-text-primary)">{cell}</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="text-xs text-(--netz-text-muted)">
				Showing first {Math.min(csvPreview.length - 1, 5)} row{csvPreview.length - 1 !== 1 ? "s" : ""} (header + data).
			</p>
		{/if}

		{#if csvError}
			<p class="text-sm text-(--netz-status-error)">{csvError}</p>
		{/if}
		<div class="flex justify-end gap-2">
			<Button variant="outline" onclick={() => showImportCsv = false}>Cancel</Button>
			<ActionButton
				onclick={importFromCsv}
				loading={importingCsv}
				loadingText="Importing..."
				disabled={!csvFile}
			>
				Import
			</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Toast notification -->
{#if toast}
	<Toast
		message={toast.message}
		type={toast.type}
		onDismiss={() => toast = null}
	/>
{/if}
