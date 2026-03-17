<!--
  @component DealStageTimeline
  Horizontal timeline showing stage progression with dates and rationale.
-->
<script lang="ts">
	import { StatusBadge } from "@netz/ui";

	interface StageEvent {
		stage: string;
		transitioned_at: string;
		rationale?: string;
		actor_name?: string;
	}

	let { timeline = [] }: { timeline: unknown[] } = $props();
	let events = $derived(timeline as StageEvent[]);
</script>

<div class="flex items-center gap-1 overflow-x-auto rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3">
	{#each events as event, i (i)}
		<div class="flex shrink-0 items-center gap-2">
			<div class="flex flex-col items-center gap-1">
				<StatusBadge status={event.stage} type="deal" />
				<span class="text-[10px] text-[var(--netz-text-muted)]">
					{event.transitioned_at ? new Date(event.transitioned_at).toLocaleDateString() : ""}
				</span>
			</div>
			{#if i < events.length - 1}
				<div class="h-px w-8 bg-[var(--netz-border)]"></div>
			{/if}
		</div>
	{/each}
</div>
