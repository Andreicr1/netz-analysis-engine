<!--
  Level 3 Sheet — Share Classes by Fund.
  Nested on top of Level 2. Shows share class details for registered funds.
  Terminal level — no further drill-down.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import * as Sheet from "@investintell/ui/components/ui/sheet";
	import { DataTable, formatAUM, formatPercent, formatCompact, formatDate } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { ChevronLeft, Loader2, Download } from "lucide-svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { runScreenerImport, ScreenerImportError, type ImportProgress } from "$lib/api/screener-import";
	import type { ShareClassItem, FundClassesResponse } from "$lib/types/catalog";
	import type { ColumnDef } from "@tanstack/svelte-table";

	interface Props {
		open: boolean;
		fundId: string;
		fundName: string;
		managerName?: string;
		onClose: () => void;
		onImport?: (classItem: ShareClassItem) => void;
	}

	let {
		open = $bindable(false),
		fundId,
		fundName,
		managerName = "",
		onClose,
		onImport,
	}: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let classes = $state<ShareClassItem[]>([]);
	let loading = $state(false);
	let totalClasses = $state(0);
	let importing = $state<string | null>(null);
	// Live import progress per class_id — driven by SSE events from
	// the Phase 4 job-or-stream endpoint. Components read this to
	// render a progress indicator next to the spinner.
	let importProgress = $state<Record<string, ImportProgress>>({});
	let importError = $state<string | null>(null);

	$effect(() => {
		if (open && fundId) {
			fetchClasses();
		}
	});

	async function fetchClasses() {
		loading = true;
		try {
			const result = await api.get<FundClassesResponse>(
				`/screener/funds/${encodeURIComponent(fundId)}/classes`,
			);
			classes = result.classes ?? [];
			totalClasses = result.total_classes ?? 0;
		} catch {
			classes = [];
			totalClasses = 0;
		} finally {
			loading = false;
		}
	}

	async function handleImport(item: ShareClassItem) {
		if (!item.ticker || importing) return;
		importing = item.class_id;
		importError = null;
		try {
			// Phase 4 — job-or-stream + Idempotency-Key. The helper
			// computes the SHA-256 idempotency key, posts the
			// 202 enqueue, and consumes the SSE channel. A second
			// click within the server's TTL window receives the same
			// job_id back via the @idempotent decorator and the
			// onProgress callback fast-forwards through cached events.
			const run = await runScreenerImport({
				identifier: item.ticker,
				blockId: null,
				strategy: null,
				getToken,
				onProgress: (p) => {
					importProgress = { ...importProgress, [item.class_id]: p };
				},
			});
			await run.result();
			onImport?.(item);
		} catch (err) {
			if (err instanceof ScreenerImportError) {
				importError = err.message;
			} else {
				importError = err instanceof Error ? err.message : "Import failed";
			}
		} finally {
			importing = null;
			// Drop progress entry once the job is settled.
			const next = { ...importProgress };
			delete next[item.class_id];
			importProgress = next;
		}
	}

	const columns: ColumnDef<ShareClassItem, unknown>[] = [
		{
			accessorKey: "class_name",
			header: "Share Class",
			cell: ({ row }) => row.original.class_name ?? row.original.class_id,
			enableSorting: true,
		},
		{
			accessorKey: "ticker",
			header: "Ticker",
			cell: ({ row }) => row.original.ticker ?? "\u2014",
			enableSorting: true,
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
			accessorKey: "net_assets",
			header: "NAV",
			cell: ({ row }) => {
				const val = row.original.net_assets;
				if (val == null) return "\u2014";
				return formatCompact(val);
			},
			enableSorting: true,
			meta: { numeric: true },
		},
		{
			accessorKey: "avg_annual_return_pct",
			header: "1Y Return",
			cell: ({ row }) => {
				const val = row.original.avg_annual_return_pct;
				if (val == null) return "\u2014";
				return formatPercent(val);
			},
			enableSorting: true,
			meta: { numeric: true },
		},
		{
			accessorKey: "perf_inception_date",
			header: "Inception",
			cell: ({ row }) => {
				const val = row.original.perf_inception_date;
				if (!val) return "\u2014";
				return formatDate(new Date(val));
			},
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
		class="!w-[min(70vw,900px)] !max-w-none flex flex-col p-0 gap-0"
		showCloseButton={false}
	>
		<!-- Header -->
		<div class="flex items-center gap-3 border-b px-4 py-3">
			<button
				class="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
				onclick={onClose}
				aria-label="Back"
			>
				<ChevronLeft class="size-5" />
			</button>
			<div class="flex-1 min-w-0">
				<h2 class="text-base font-semibold truncate">{fundName} — Share Classes</h2>
				<div class="flex items-center gap-3 text-xs text-muted-foreground">
					<span>CIK {fundId}</span>
					{#if managerName}
						<span>{managerName}</span>
					{/if}
					<span>{totalClasses} class{totalClasses !== 1 ? "es" : ""}</span>
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
					Loading share classes...
				</div>
			{:else if classes.length === 0}
				<div class="flex flex-col items-center gap-2 py-16 text-muted-foreground">
					<p class="text-sm font-medium">No share classes found</p>
					<p class="text-xs">This fund may not have disclosed share class data.</p>
				</div>
			{:else}
				<DataTable data={classes} {columns} pageSize={50} />

				<!-- Import action -->
				{#if classes.some((c) => c.ticker)}
					<div class="mt-4 flex items-center gap-2 border-t pt-4">
						<span class="text-xs text-muted-foreground">Import a share class to your universe:</span>
						<div class="flex flex-wrap gap-2">
							{#each classes.filter((c) => c.ticker) as cls (cls.class_id)}
								<Button
									variant="outline"
									size="sm"
									class="h-7 text-xs"
									disabled={importing === cls.class_id}
									onclick={() => handleImport(cls)}
								>
									{#if importing === cls.class_id}
										<Loader2 class="size-3 animate-spin mr-1" />
									{:else}
										<Download class="size-3 mr-1" />
									{/if}
									{cls.ticker}
								</Button>
							{/each}
						</div>
					</div>
				{/if}
			{/if}
		</div>
	</Sheet.Content>
</Sheet.Root>
