<script lang="ts">
	import { cn } from "../utils/cn.js";

	let {
		title,
		orgId,
		slug,
		planTier,
		status,
		freshness,
		scopeLabel = "Tenant scope",
		actions,
		class: className,
	}: {
		title: string;
		orgId: string;
		slug?: string | null;
		planTier?: string | null;
		status?: string | null;
		freshness?: string | null;
		scopeLabel?: string;
		actions?: import("svelte").Snippet;
		class?: string;
	} = $props();

	const statusStyle = $derived.by(() => {
		switch (status) {
			case "active":
				return { border: "border-l-[var(--netz-info)]", dot: "bg-[var(--netz-info)]", label: "Active" };
			case "suspended":
				return { border: "border-l-[var(--netz-warning)]", dot: "bg-[var(--netz-warning)]", label: "Suspended" };
			case "archived":
				return { border: "border-l-[var(--netz-text-muted)]", dot: "bg-[var(--netz-text-muted)]", label: "Archived" };
			default:
				return { border: "border-l-[var(--netz-info)]", dot: "bg-[var(--netz-info)]", label: status ?? "" };
		}
	});
</script>

<section
	class={cn(
		"sticky top-0 z-20 border-b border-[var(--netz-border)] bg-[var(--netz-surface)]/95 px-6 py-4 backdrop-blur",
		"border-l-4",
		statusStyle.border,
		className,
	)}
>
	<div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
		<div class="min-w-0 space-y-2">
			<p class="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--netz-text-muted)]">
				{scopeLabel}
			</p>
			<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
				<h1 class="text-xl font-semibold text-[var(--netz-text-primary)]">{title}</h1>
				<span class="inline-flex items-center rounded-full border border-[var(--netz-border)] px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
					{orgId}
				</span>
			</div>
			<div class="flex flex-wrap items-center gap-3 text-sm text-[var(--netz-text-secondary)]">
				{#if slug}
					<span>Slug: {slug}</span>
				{/if}
				{#if planTier}
					<span>Plan: {planTier}</span>
				{/if}
				{#if status}
					<span class="inline-flex items-center gap-1.5">
						<span class="h-1.5 w-1.5 rounded-full {statusStyle.dot}"></span>
						{statusStyle.label}
					</span>
				{/if}
				{#if freshness}
					<span>{freshness}</span>
				{/if}
			</div>
		</div>

		{#if actions}
			<div class="flex shrink-0 items-center gap-3">
				{@render actions()}
			</div>
		{/if}
	</div>
</section>
