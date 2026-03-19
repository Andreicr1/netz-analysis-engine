<!--
  Kanban board for deal pipeline — drag cards between stage columns.
  Uses svelte-dnd-action for drag-and-drop, ConsequenceDialog for stage mutation.
-->
<script lang="ts">
	import { dndzone, TRIGGERS, SHADOW_ITEM_MARKER_PROPERTY_NAME } from "svelte-dnd-action";
	import { ConsequenceDialog } from "@netz/ui";
	import { fade } from "svelte/transition";
	import { invalidateAll } from "$app/navigation";
	import { createClientApiClient } from "$lib/api/client";
	import type { DealStage } from "$lib/types/api";

	interface DealItem {
		id: string;
		name: string;
		stage: DealStage;
		deal_type: string;
		sponsor_name: string | null;
	}

	interface Props {
		deals: DealItem[];
		fundId: string;
		getToken: () => Promise<string>;
	}

	let { deals, fundId, getToken }: Props = $props();

	const stages: Array<{ value: DealStage; label: string }> = [
		{ value: "INTAKE", label: "Intake" },
		{ value: "QUALIFIED", label: "Qualified" },
		{ value: "IC_REVIEW", label: "IC Review" },
		{ value: "CONDITIONAL", label: "Conditional" },
		{ value: "APPROVED", label: "Approved" },
		{ value: "CONVERTED_TO_ASSET", label: "Converted" },
		{ value: "REJECTED", label: "Rejected" },
		{ value: "CLOSED", label: "Closed" },
	];

	const stageLabels: Record<DealStage, string> = Object.fromEntries(
		stages.map((s) => [s.value, s.label]),
	) as Record<DealStage, string>;

	interface KanbanCard {
		id: string;
		name: string;
		stage: DealStage;
		deal_type: string;
		sponsor_name: string | null;
		[SHADOW_ITEM_MARKER_PROPERTY_NAME]?: boolean;
	}

	interface ColumnData {
		stage: DealStage;
		label: string;
		items: KanbanCard[];
	}

	function buildColumns(dealList: DealItem[]): ColumnData[] {
		return stages.map((s) => ({
			stage: s.value,
			label: s.label,
			items: dealList
				.filter((d) => d.stage === s.value)
				.map((d) => ({ ...d })),
		}));
	}

	// svelte-ignore state_referenced_locally
	let columns = $state<ColumnData[]>(buildColumns(deals));

	// Sync when deals prop changes
	$effect(() => {
		columns = buildColumns(deals);
	});

	// ── Confirmation dialog state ──
	let confirmOpen = $state(false);
	let pendingMove = $state<{
		dealId: string;
		dealName: string;
		fromStage: DealStage;
		toStage: DealStage;
		rollback: ColumnData[];
	} | null>(null);
	let moveError = $state<string | null>(null);

	function handleConsider(stageIdx: number, e: CustomEvent<{ items: KanbanCard[]; info: { trigger: string } }>) {
		columns[stageIdx]!.items = e.detail.items;
	}

	function handleFinalize(stageIdx: number, e: CustomEvent<{ items: KanbanCard[]; info: { trigger: string; id: string } }>) {
		const targetStage = columns[stageIdx]!.stage;
		const movedCard = e.detail.items.find(
			(item) => item.stage !== targetStage && !item[SHADOW_ITEM_MARKER_PROPERTY_NAME],
		);

		columns[stageIdx]!.items = e.detail.items;

		if (movedCard && movedCard.stage !== targetStage) {
			const snapshot = buildColumns(deals);
			pendingMove = {
				dealId: movedCard.id,
				dealName: movedCard.name,
				fromStage: movedCard.stage,
				toStage: targetStage,
				rollback: snapshot,
			};
			confirmOpen = true;
		}
	}

	async function confirmStageMove() {
		if (!pendingMove) return;
		moveError = null;

		const { dealId, toStage, rollback } = pendingMove;

		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/pipeline/deals/${dealId}/stage?fund_id=${fundId}`, {
				to_stage: toStage,
			});
			// Update the card's stage in our local state
			for (const col of columns) {
				for (const card of col.items) {
					if (card.id === dealId) {
						card.stage = toStage;
					}
				}
			}
			pendingMove = null;
			await invalidateAll();
		} catch (err) {
			columns = rollback;
			pendingMove = null;
			moveError = err instanceof Error ? err.message : "Failed to move deal";
			setTimeout(() => (moveError = null), 5000);
		}
	}

	function cancelStageMove() {
		if (pendingMove) {
			columns = pendingMove.rollback;
			pendingMove = null;
		}
	}
</script>

<div class="flex gap-3 overflow-x-auto pb-4" role="list" aria-label="Pipeline Kanban board">
	{#each columns as column, idx}
		<div
			class="flex w-64 min-w-64 shrink-0 flex-col rounded-lg border border-(--netz-border) bg-(--netz-surface-alt)"
			role="listitem"
			aria-label="{column.label} column, {column.items.length} deals"
		>
			<!-- Column header -->
			<div class="flex items-center justify-between border-b border-(--netz-border) px-3 py-2">
				<h3 class="text-xs font-semibold uppercase tracking-wider text-(--netz-text-secondary)">
					{column.label}
				</h3>
				<span class="flex h-5 min-w-5 items-center justify-center rounded-full bg-(--netz-surface) px-1.5 text-xs font-medium text-(--netz-text-secondary)">
					{column.items.length}
				</span>
			</div>

			<!-- Drop zone -->
			<div
				class="flex min-h-32 flex-1 flex-col gap-2 p-2"
				use:dndzone={{ items: column.items, flipDurationMs: 200, dropTargetStyle: {} }}
				onconsider={(e) => handleConsider(idx, e)}
				onfinalize={(e) => handleFinalize(idx, e)}
				role="list"
				aria-label="{column.label} deals"
			>
				{#each column.items as card (card.id)}
					<a
						href="/funds/{fundId}/pipeline/{card.id}"
						class="block rounded-md border border-(--netz-border) bg-(--netz-surface) p-3 shadow-sm transition-shadow hover:shadow-md"
						class:opacity-50={card[SHADOW_ITEM_MARKER_PROPERTY_NAME]}
						aria-label="Deal: {card.name}"
					>
						<p class="text-sm font-medium text-(--netz-text-primary) line-clamp-2">
							{card.name}
						</p>
						{#if card.deal_type || card.sponsor_name}
							<p class="mt-1.5 text-xs text-(--netz-text-muted) line-clamp-1">
								{[card.deal_type, card.sponsor_name].filter(Boolean).join(" · ")}
							</p>
						{/if}
					</a>
				{/each}
			</div>
		</div>
	{/each}
</div>

<!-- Error toast -->
{#if moveError}
	<div transition:fade={{ duration: 200 }} class="fixed bottom-4 right-4 z-50 rounded-lg border border-(--netz-danger) bg-(--netz-surface) px-4 py-3 shadow-lg" role="alert">
		<p class="text-sm text-(--netz-danger)">{moveError}</p>
	</div>
{/if}

<!-- Consequence dialog for stage move -->
<ConsequenceDialog
	bind:open={confirmOpen}
	title="Move deal to {pendingMove ? stageLabels[pendingMove.toStage] : ''}"
	impactSummary="This will change the deal's pipeline stage. The move will be recorded in the deal audit trail."
	confirmLabel="Move deal"
	cancelLabel="Cancel"
	metadata={pendingMove
		? [
				{ label: "Deal", value: pendingMove.dealName, emphasis: true },
				{ label: "From", value: stageLabels[pendingMove.fromStage] },
				{ label: "To", value: stageLabels[pendingMove.toStage], emphasis: true },
			]
		: []}
	onConfirm={confirmStageMove}
	onCancel={cancelStageMove}
/>
