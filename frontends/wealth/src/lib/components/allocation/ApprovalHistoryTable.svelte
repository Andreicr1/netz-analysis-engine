<!--
  PR-A26.3 Section G — Approval history table.

  Collapsible, offset/limit pagination via refetch through the API
  client. Active/Superseded badge computed from is_active server-side.
-->
<script lang="ts">
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import { CheckCircle2, AlertTriangle, ChevronDown, ChevronRight } from "lucide-svelte";
	import type {
		AllocationProfile,
		ApprovalHistoryResponse,
	} from "$lib/types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		history: ApprovalHistoryResponse;
		apiGet: <T>(path: string) => Promise<T>;
	}
	let { profile, history, apiGet }: Props = $props();

	let expanded = $state(false);
	let offset = $state(0);
	const limit = 5;
	let override = $state<ApprovalHistoryResponse | null>(null);
	const current = $derived(override ?? history);
	let loading = $state(false);
	let errorMsg = $state<string | null>(null);

	async function fetchPage(nextOffset: number): Promise<void> {
		loading = true;
		errorMsg = null;
		try {
			const resp = await apiGet<ApprovalHistoryResponse>(
				`/portfolio/profiles/${profile}/approval-history?limit=${limit}&offset=${nextOffset}`,
			);
			override = resp;
			offset = nextOffset;
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : "Failed to load";
		} finally {
			loading = false;
		}
	}

	function truncate(text: string | null, n = 60): string {
		if (!text) return "—";
		return text.length > n ? `${text.slice(0, n)}…` : text;
	}

	const canPrev = $derived(offset > 0);
	const canNext = $derived(offset + limit < current.total);
</script>

<section class="rounded-lg border border-border bg-card">
	<button
		type="button"
		class="w-full px-4 py-3 flex items-center justify-between text-left"
		onclick={() => (expanded = !expanded)}
		aria-expanded={expanded}
	>
		<div class="flex items-center gap-2">
			{#if expanded}
				<ChevronDown class="w-4 h-4 text-muted-foreground" />
			{:else}
				<ChevronRight class="w-4 h-4 text-muted-foreground" />
			{/if}
			<h2 class="text-base font-medium text-foreground">Approval History</h2>
			<span class="text-xs text-muted-foreground">({current.total})</span>
		</div>
	</button>

	{#if expanded}
		<div class="border-t border-border p-3">
			{#if errorMsg}
				<p class="text-xs text-destructive mb-2">{errorMsg}</p>
			{/if}

			{#if current.entries.length === 0}
				<p class="text-sm text-muted-foreground py-6 text-center">
					No approvals yet.
				</p>
			{:else}
				<div class="overflow-x-auto rounded-md border border-border">
					<table class="w-full text-xs">
						<thead class="bg-muted/40 text-muted-foreground uppercase tracking-wide">
							<tr>
								<th class="text-left px-3 py-1.5">Status</th>
								<th class="text-left px-3 py-1.5">Approved At</th>
								<th class="text-left px-3 py-1.5">Approved By</th>
								<th class="text-right px-3 py-1.5">CVaR</th>
								<th class="text-right px-3 py-1.5">Expected Return</th>
								<th class="text-center px-3 py-1.5">Feasible</th>
								<th class="text-left px-3 py-1.5">Message</th>
							</tr>
						</thead>
						<tbody>
							{#each current.entries as entry (entry.approval_id)}
								<tr class="border-t border-border">
									<td class="px-3 py-1.5">
										{#if entry.is_active}
											<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-success/10 text-success">
												Active
											</span>
										{:else}
											<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
												Superseded
											</span>
										{/if}
									</td>
									<td class="px-3 py-1.5 text-foreground">
										{formatDateTime(entry.approved_at)}
									</td>
									<td class="px-3 py-1.5 text-foreground">{entry.approved_by}</td>
									<td class="px-3 py-1.5 text-right tabular-nums">
										{entry.cvar_at_approval !== null
											? formatPercent(entry.cvar_at_approval)
											: "—"}
									</td>
									<td class="px-3 py-1.5 text-right tabular-nums">
										{entry.expected_return_at_approval !== null
											? formatPercent(entry.expected_return_at_approval)
											: "—"}
									</td>
									<td class="px-3 py-1.5 text-center">
										{#if entry.cvar_feasible_at_approval}
											<CheckCircle2 class="w-4 h-4 text-success inline" />
										{:else}
											<AlertTriangle class="w-4 h-4 text-warning inline" />
										{/if}
									</td>
									<td class="px-3 py-1.5 text-muted-foreground" title={entry.operator_message ?? ""}>
										{truncate(entry.operator_message)}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}

			<div class="mt-3 flex items-center justify-end gap-2">
				<button
					type="button"
					class="text-xs px-3 py-1 rounded-md border border-border text-muted-foreground hover:text-foreground disabled:opacity-40"
					disabled={!canPrev || loading}
					onclick={() => void fetchPage(Math.max(0, offset - limit))}
				>
					Previous
				</button>
				<span class="text-xs text-muted-foreground">
					{offset + 1}–{Math.min(offset + current.entries.length, current.total)} of {current.total}
				</span>
				<button
					type="button"
					class="text-xs px-3 py-1 rounded-md border border-border text-muted-foreground hover:text-foreground disabled:opacity-40"
					disabled={!canNext || loading}
					onclick={() => void fetchPage(offset + limit)}
				>
					Next
				</button>
			</div>
		</div>
	{/if}
</section>
