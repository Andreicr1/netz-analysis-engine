<!--
  Fund context layout — shows fund name header + fund-scoped navigation.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { PageHeader } from "@netz/ui";
	import type { Snippet } from "svelte";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: Snippet } = $props();

	let fundNav = $derived([
		{ label: "Pipeline", href: `/funds/${data.fund.id}/pipeline` },
		{ label: "Portfolio", href: `/funds/${data.fund.id}/portfolio` },
		{ label: "Documents", href: `/funds/${data.fund.id}/documents` },
		{ label: "Reporting", href: `/funds/${data.fund.id}/reporting` },
	]);

	function isActive(href: string): boolean {
		return $page.url.pathname.startsWith(href);
	}
</script>

<div class="flex h-full flex-col">
	<PageHeader title={data.fund.name}>
		{#snippet actions()}
			<nav class="flex gap-1">
				{#each fundNav as item (item.href)}
					<a
						href={item.href}
						class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
						class:bg-[var(--netz-primary)]/10={isActive(item.href)}
						class:text-[var(--netz-primary)]={isActive(item.href)}
						class:text-[var(--netz-text-secondary)]={!isActive(item.href)}
						class:hover:bg-[var(--netz-surface-alt)]={!isActive(item.href)}
					>
						{item.label}
					</a>
				{/each}
			</nav>
		{/snippet}
	</PageHeader>

	<div class="flex-1 overflow-y-auto">
		{@render children()}
	</div>
</div>
