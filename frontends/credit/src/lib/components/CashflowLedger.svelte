<!--
  @component CashflowLedger
  Deal cashflow ledger: list, register, edit, and delete cashflow entries.
  Used in the "Cashflows & Performance" tab of the deal detail page.
-->
<script lang="ts">
	import { DataTable, Button, ConsequenceDialog, FormField, EmptyState } from "@netz/ui";
	import { formatCurrency, formatDate, createOptimisticMutation } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import type { ColumnDef } from "@tanstack/svelte-table";

	// ── Types matching DealCashflowOut and DealCashflowCreate from api.d.ts ──
	interface DealCashflowOut {
		id: string;
		deal_id: string;
		fund_id: string;
		flow_type: string;
		amount: number;
		currency: string;
		flow_date: string;
		description: string | null;
		reference: string | null;
		created_at: string;
		updated_at: string;
	}

	interface DealCashflowCreate {
		flow_type: string;
		amount: number;
		currency: string;
		flow_date: string;
		description?: string | null;
		reference?: string | null;
	}

	const FLOW_TYPE_LABELS: Record<string, string> = {
		disbursement: "Desembolso",
		repayment_principal: "Amortização",
		repayment_interest: "Juros",
		fee: "Taxa",
		distribution: "Distribuição",
		capital_call: "Chamada de Capital",
	};

	const FLOW_TYPES = Object.keys(FLOW_TYPE_LABELS);

	let {
		fundId,
		dealId,
		initialCashflows = [],
	}: {
		fundId: string;
		dealId: string;
		initialCashflows?: DealCashflowOut[];
	} = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── State ──
	// Use a getter to avoid "state_referenced_locally" — initial prop is passed in once
	let cashflows = $state<DealCashflowOut[]>([]);
	$effect(() => {
		cashflows = initialCashflows;
	});
	let error = $state<string | null>(null);

	// Register dialog
	let showRegister = $state(false);
	let registerFlowType = $state("disbursement");
	let registerAmount = $state("");
	let registerCurrency = $state("USD");
	let registerDate = $state(new Date().toISOString().split("T")[0]);
	let registerDescription = $state("");
	let registerReference = $state("");

	// Edit dialog
	let showEdit = $state(false);
	let editTarget = $state<DealCashflowOut | null>(null);
	let editFlowType = $state("disbursement");
	let editAmount = $state("");
	let editCurrency = $state("USD");
	let editDate = $state("");
	let editDescription = $state("");
	let editReference = $state("");

	// Delete dialog
	let showDelete = $state(false);
	let deleteTarget = $state<DealCashflowOut | null>(null);

	// ── Optimistic mutation for cashflow list ──
	const cashflowMutation = createOptimisticMutation<DealCashflowOut[]>({
		getState: () => cashflows,
		setState: (value) => { cashflows = value; },
		request: async (optimisticValue) => optimisticValue,
	});

	// ── Table columns ──
	const columns: ColumnDef<Record<string, unknown>, unknown>[] = [
		{
			id: "flow_date",
			accessorKey: "flow_date",
			header: "Data",
			cell: (info) => formatDate(String(info.getValue())),
		},
		{
			id: "flow_type",
			accessorKey: "flow_type",
			header: "Tipo",
			cell: (info) => FLOW_TYPE_LABELS[String(info.getValue())] ?? String(info.getValue()),
		},
		{
			id: "amount",
			accessorKey: "amount",
			header: "Valor",
			cell: (info) => formatCurrency(Number(info.getValue())),
		},
		{
			id: "currency",
			accessorKey: "currency",
			header: "Moeda",
		},
		{
			id: "reference",
			accessorKey: "reference",
			header: "Referência",
			cell: (info) => (info.getValue() != null ? String(info.getValue()) : "—"),
		},
		{
			id: "actions",
			header: "Ações",
			cell: (info) => {
				// Rendered via snippet below — returned as marker
				return info.row.original;
			},
		},
	];

	// ── API helpers ──
	function getApi() {
		return createClientApiClient(getToken);
	}

	async function handleRegister() {
		error = null;
		const amt = parseFloat(registerAmount);
		if (!registerFlowType || isNaN(amt) || amt <= 0) {
			error = "Informe tipo, valor positivo e data.";
			throw new Error(error);
		}

		const body: DealCashflowCreate = {
			flow_type: registerFlowType,
			amount: amt,
			currency: registerCurrency,
			flow_date: registerDate,
			description: registerDescription.trim() || null,
			reference: registerReference.trim() || null,
		};

		// Optimistic append with placeholder id
		const optimistic: DealCashflowOut = {
			id: `_optimistic_${Date.now()}`,
			deal_id: dealId,
			fund_id: fundId,
			flow_type: body.flow_type,
			amount: body.amount,
			currency: body.currency,
			flow_date: body.flow_date,
			description: body.description ?? null,
			reference: body.reference ?? null,
			created_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		};
		cashflowMutation.mutate([optimistic, ...cashflows]).catch(() => {});

		try {
			const api = getApi();
			const created = await api.post<DealCashflowOut>(
				`/funds/${fundId}/deals/${dealId}/cashflows`,
				body,
			);
			// Replace optimistic with real record
			cashflows = [created, ...cashflows.filter((c) => c.id !== optimistic.id)];
			showRegister = false;
			resetRegisterForm();
		} catch (e) {
			cashflows = cashflows.filter((c) => c.id !== optimistic.id);
			error = e instanceof Error ? e.message : "Falha ao registrar cashflow.";
			throw e;
		}
	}

	function openEdit(cf: DealCashflowOut) {
		editTarget = cf;
		editFlowType = cf.flow_type;
		editAmount = String(cf.amount);
		editCurrency = cf.currency;
		editDate = cf.flow_date;
		editDescription = cf.description ?? "";
		editReference = cf.reference ?? "";
		error = null;
		showEdit = true;
	}

	async function handleEdit() {
		if (!editTarget) return;
		error = null;
		const amt = parseFloat(editAmount);
		if (!editFlowType || isNaN(amt) || amt <= 0) {
			error = "Informe tipo, valor positivo e data.";
			throw new Error(error);
		}

		const body: DealCashflowCreate = {
			flow_type: editFlowType,
			amount: amt,
			currency: editCurrency,
			flow_date: editDate,
			description: editDescription.trim() || null,
			reference: editReference.trim() || null,
		};

		try {
			const api = getApi();
			const updated = await api.patch<DealCashflowOut>(
				`/funds/${fundId}/deals/${dealId}/cashflows/${editTarget.id}`,
				body,
			);
			cashflows = cashflows.map((c) => (c.id === editTarget!.id ? updated : c));
			showEdit = false;
			editTarget = null;
		} catch (e) {
			error = e instanceof Error ? e.message : "Falha ao editar cashflow.";
			throw e;
		}
	}

	function openDelete(cf: DealCashflowOut) {
		deleteTarget = cf;
		error = null;
		showDelete = true;
	}

	async function handleDelete() {
		if (!deleteTarget) return;
		error = null;
		const targetId = deleteTarget.id;
		const previousCashflows = cashflows;
		cashflows = cashflows.filter((c) => c.id !== targetId);

		try {
			const api = getApi();
			await api.delete(`/funds/${fundId}/deals/${dealId}/cashflows/${targetId}`);
			showDelete = false;
			deleteTarget = null;
			await invalidateAll();
		} catch (e) {
			cashflows = previousCashflows;
			error = e instanceof Error ? e.message : "Falha ao excluir cashflow.";
			throw e;
		}
	}

	function resetRegisterForm() {
		registerFlowType = "disbursement";
		registerAmount = "";
		registerCurrency = "USD";
		registerDate = new Date().toISOString().split("T")[0];
		registerDescription = "";
		registerReference = "";
	}

	let tableData = $derived(cashflows as Record<string, unknown>[]);
</script>

<div class="space-y-4">
	<!-- Header with register button -->
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-lg font-semibold text-[var(--netz-text-primary)]">Cashflows</h3>
			<p class="text-sm text-[var(--netz-text-muted)]">
				Registro de desembolsos, amortizações e distribuições deste deal.
			</p>
		</div>
		<Button
			onclick={() => {
				resetRegisterForm();
				error = null;
				showRegister = true;
			}}
		>
			Registrar Cashflow
		</Button>
	</div>

	{#if error}
		<div
			class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]"
		>
			{error}
		</div>
	{/if}

	<!-- Cashflow table with action snippets injected via expandedRow trick — actions rendered inline -->
	{#if tableData.length === 0}
		<EmptyState
			title="Nenhum cashflow registrado"
			description="Registre o primeiro desembolso ou amortização para acompanhar a performance do deal."
		/>
	{:else}
		<div class="overflow-x-auto">
			<div class="rounded-md border border-[var(--netz-border)]">
				<table class="w-full caption-bottom text-sm">
					<thead class="bg-[var(--netz-brand-primary)]">
						<tr>
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">Data</th>
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">Tipo</th>
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">Valor</th>
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">Moeda</th>
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">Referência</th>
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">Ações</th>
						</tr>
					</thead>
					<tbody>
						{#each cashflows as cf (cf.id)}
							<tr
								class="border-b border-[var(--netz-border)] transition-colors hover:bg-[var(--netz-surface-alt)]"
							>
								<td class="px-4 py-3 align-middle text-[var(--netz-text-primary)]">
									{formatDate(cf.flow_date)}
								</td>
								<td class="px-4 py-3 align-middle text-[var(--netz-text-primary)]">
									{FLOW_TYPE_LABELS[cf.flow_type] ?? cf.flow_type}
								</td>
								<td class="px-4 py-3 align-middle font-mono text-[var(--netz-text-primary)]">
									{formatCurrency(cf.amount)}
								</td>
								<td class="px-4 py-3 align-middle text-[var(--netz-text-primary)]">
									{cf.currency}
								</td>
								<td class="px-4 py-3 align-middle text-[var(--netz-text-muted)]">
									{cf.reference ?? "—"}
								</td>
								<td class="px-4 py-3 align-middle">
									<div class="flex gap-2">
										<Button variant="outline" size="sm" onclick={() => openEdit(cf)}>
											Editar
										</Button>
										<Button variant="destructive" size="sm" onclick={() => openDelete(cf)}>
											Excluir
										</Button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>

<!-- Register Cashflow Dialog -->
<ConsequenceDialog
	bind:open={showRegister}
	title="Registrar Cashflow"
	impactSummary="This will affect MOIC and IRR calculations for this deal."
	destructive={false}
	requireRationale={false}
	confirmLabel="Registrar"
	onConfirm={handleRegister}
	onCancel={() => {
		showRegister = false;
		error = null;
	}}
>
	{#snippet children()}
		<div class="space-y-4">
			<FormField label="Tipo" required>
				<select
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={registerFlowType}
				>
					{#each FLOW_TYPES as ft (ft)}
						<option value={ft}>{FLOW_TYPE_LABELS[ft]}</option>
					{/each}
				</select>
			</FormField>

			<FormField label="Valor" required>
				<input
					type="number"
					min="0.01"
					step="0.01"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={registerAmount}
					placeholder="0.00"
				/>
			</FormField>

			<FormField label="Moeda">
				<input
					type="text"
					maxlength="3"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={registerCurrency}
					placeholder="USD"
				/>
			</FormField>

			<FormField label="Data" required>
				<input
					type="date"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={registerDate}
				/>
			</FormField>

			<FormField label="Descrição">
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={registerDescription}
					placeholder="Descrição opcional"
				/>
			</FormField>

			<FormField label="Referência">
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={registerReference}
					placeholder="Número de referência opcional"
				/>
			</FormField>

			{#if error}
				<p class="text-sm text-[var(--netz-status-error)]">{error}</p>
			{/if}
		</div>
	{/snippet}
</ConsequenceDialog>

<!-- Edit Cashflow Dialog -->
<ConsequenceDialog
	bind:open={showEdit}
	title="Editar Cashflow"
	impactSummary="This will affect MOIC and IRR calculations for this deal."
	destructive={false}
	requireRationale={false}
	confirmLabel="Salvar Alterações"
	onConfirm={handleEdit}
	onCancel={() => {
		showEdit = false;
		editTarget = null;
		error = null;
	}}
>
	{#snippet children()}
		<div class="space-y-4">
			<FormField label="Tipo" required>
				<select
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={editFlowType}
				>
					{#each FLOW_TYPES as ft (ft)}
						<option value={ft}>{FLOW_TYPE_LABELS[ft]}</option>
					{/each}
				</select>
			</FormField>

			<FormField label="Valor" required>
				<input
					type="number"
					min="0.01"
					step="0.01"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={editAmount}
					placeholder="0.00"
				/>
			</FormField>

			<FormField label="Moeda">
				<input
					type="text"
					maxlength="3"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={editCurrency}
					placeholder="USD"
				/>
			</FormField>

			<FormField label="Data" required>
				<input
					type="date"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={editDate}
				/>
			</FormField>

			<FormField label="Descrição">
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={editDescription}
					placeholder="Descrição opcional"
				/>
			</FormField>

			<FormField label="Referência">
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={editReference}
					placeholder="Número de referência opcional"
				/>
			</FormField>

			{#if error}
				<p class="text-sm text-[var(--netz-status-error)]">{error}</p>
			{/if}
		</div>
	{/snippet}
</ConsequenceDialog>

<!-- Delete Cashflow Dialog -->
<ConsequenceDialog
	bind:open={showDelete}
	title="Excluir Cashflow"
	impactSummary="This will affect MOIC and IRR calculations for this deal. This action cannot be undone."
	destructive={true}
	requireRationale={false}
	confirmLabel="Excluir Cashflow"
	metadata={deleteTarget
		? [
				{
					label: "Tipo",
					value: FLOW_TYPE_LABELS[deleteTarget.flow_type] ?? deleteTarget.flow_type,
					emphasis: true,
				},
				{ label: "Valor", value: formatCurrency(deleteTarget.amount) },
				{ label: "Data", value: formatDate(deleteTarget.flow_date) },
			]
		: []}
	onConfirm={handleDelete}
	onCancel={() => {
		showDelete = false;
		deleteTarget = null;
		error = null;
	}}
/>
