<!--
  @component TaskInbox
  Displays action items: deals awaiting IC, docs pending review, etc.
-->
<script lang="ts">
	import { StatusBadge, Card } from "@netz/ui";
	import { resolveCreditStatus } from "$lib/utils/status-maps";

	interface Task {
		id: string;
		title: string;
		type: string;
		priority: string;
		due_date?: string;
		link?: string;
	}

	let { tasks = [] }: { tasks: unknown[] } = $props();

	let typedTasks = $derived((tasks as Task[]).slice(0, 10));
</script>

{#if typedTasks.length === 0}
	<Card class="p-4">
		<p class="text-sm text-[var(--netz-text-muted)]">No pending tasks.</p>
	</Card>
{:else}
	<Card class="divide-y divide-[var(--netz-border)]">
		{#each typedTasks as task (task.id)}
			<a
				href={task.link ?? "#"}
				class="flex items-center justify-between px-4 py-3 transition-colors hover:bg-[var(--netz-surface-alt)]"
			>
				<div class="flex items-center gap-3">
					<StatusBadge status={task.priority} type="risk" resolve={resolveCreditStatus} />
					<div>
						<p class="text-sm font-medium text-[var(--netz-text-primary)]">{task.title}</p>
						<p class="text-xs text-[var(--netz-text-muted)]">{task.type}</p>
					</div>
				</div>
				{#if task.due_date}
					<span class="text-xs text-[var(--netz-text-muted)]">{task.due_date}</span>
				{/if}
			</a>
		{/each}
	</Card>
{/if}
