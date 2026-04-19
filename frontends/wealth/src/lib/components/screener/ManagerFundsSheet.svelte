<!--
  Level 2 Sheet — Funds by Manager.
  Opens from the right showing all funds for a specific manager (via catalog endpoint).
  Row click opens Level 3 (share classes).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import * as Sheet from "@investintell/ui/components/ui/sheet";
	import { DataTable, formatAUM, formatPercent, formatCompact } from "@investintell/ui";
	import { ChevronLeft, Building2, Loader2 } from "lucide-svelte";
	import { createClientApiClient } from "$wealth/api/client";
	import type { UnifiedFundItem, UnifiedCatalogPage } from "$wealth/types/catalog";
	import { FUND_TYPE_LABELS } from "$wealth/types/catalog";
	import type { ColumnDef } from "@tanstack/svelte-table";

	interface Props {
		open: boolean;
		managerId: string;
		managerName: string;
		managerAum?: number | null;
		onClose: () => void;
		onFundClick: (fund: UnifiedFundItem) => void;
		onImport?: (fund: UnifiedFundItem) => void;
	}

	let {
		open = $bindable(false),
		managerId,
		managerName,
		managerAum = null,
		onClose,
		onFundClick,
		onImport,
	}: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let funds = $state<UnifiedFundItem[]>([]);
	let loading = $state(false);
	let totalFunds = $state(0);

	// Fetch funds when sheet opens or managerId changes
	$effect(() => {
		if (open && managerId) {
			fetchFunds();
		}
	});

	async function fetchFunds() {
		loading = true;
		try {
			const result = await api.get<UnifiedCatalogPage>("/screener/catalog", {
				manager_id: managerId,
				has_nav: "true",
				has_aum: "false",
				page_size: "200",
			});
			funds = result.items ?? [];
			totalFunds = result.total ?? 0;
		} catch {
			funds = [];
			totalFunds = 0;
		} finally {
			loading = false;
		}
	}

	function fundTypeLabel(ft: string): string {
		return FUND_TYPE_LABELS[ft] ?? ft.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	const columns: ColumnDef<UnifiedFundItem, unknown>[] = [
		{
			accessorKey: "name",
			header: "Fund Name",
			cell: ({ row }) => row.original.name || "Unnamed Fund",
			enableSorting: true,
		},
		{
			accessorKey: "fund_type",
			header: "Type",
			cell: ({ row }) => fundTypeLabel(row.original.fund_type),
			enableSorting: true,
		},
		{
			accessorKey: "aum",
			header: "AUM",
			cell: ({ row }) => (row.original.aum != null ? formatCompact(row.original.aum) : "\u2014"),
			enableSorting: true,
			meta: { numeric: true },
		},
		{
			accessorKey: "avg_annual_return_1y",
			header: "1Y Return",
			cell: ({ row }) => {
				const val = row.original.avg_annual_return_1y;
				if (val == null) return "\u2014";
				return formatPercent(val);
			},
			enableSorting: true,
			meta: { numeric: true },
		},
		{
			accessorKey: "expense_ratio_pct",
			header: "Expense Ratio",
			cell: ({ row }) => {
				const val = row.original.expense_ratio_pct;
				if (val == null) return "\u2014";
				return formatPercent(val);
			},
			enableSorting: true,
			meta: { numeric: true },
		},
		{
			accessorKey: "strategy_label",
			header: "Strategy",
			cell: ({ row }) => row.original.strategy_label ?? "\u2014",
			enableSorting: true,
		},
	];
</script>

<Sheet.Root
	bind:open
	onOpenChange={(v) => {
		if (!v) onClose();
	}}
>
	<Sheet.Content
		side="right"
		class="!w-[min(85vw,1200px)] !max-w-none flex flex-col p-0 gap-0"
		showCloseButton={false}
	>
		<!-- Header -->
		<div class="flex items-center gap-3 border-b px-4 py-3">
			<button
				class="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
				onclick={onClose}
				aria-label="Close"
			>
				<ChevronLeft class="size-5" />
			</button>
			<div class="flex-1 min-w-0">
				<h2 class="text-base font-semibold truncate">{managerName}</h2>
				<div class="flex items-center gap-3 text-xs text-muted-foreground">
					<span class="flex items-center gap-1">
						<Building2 class="size-3" />
						CRD {managerId}
					</span>
					{#if managerAum != null}
						<span>AUM {formatAUM(managerAum)}</span>
					{/if}
					<span>{totalFunds} fund{totalFunds !== 1 ? "s" : ""}</span>
				</div>
			</div>
			<button
				class="inline-flex items-center justify-center rounded-md border px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
				onclick={onClose}
				aria-label="Close sheet"
			>
				Esc
			</button>
		</div>

		<!-- Content -->
		<div class="flex-1 min-h-0 overflow-y-auto p-4">
			{#if loading}
				<div class="flex items-center justify-center py-16 text-muted-foreground">
					<Loader2 class="size-5 animate-spin mr-2" />
					Loading funds...
				</div>
			{:else}
				<DataTable
					data={funds}
					{columns}
					pageSize={50}
					onRowClick={(row) => onFundClick(row as UnifiedFundItem)}
				/>
			{/if}
		</div>
	</Sheet.Content>
</Sheet.Root>
