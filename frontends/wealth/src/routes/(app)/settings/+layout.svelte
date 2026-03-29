<!--
  Settings layout — internal nav for Config and System sub-pages.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { PageHeader } from "@investintell/ui";
	import type { Snippet } from "svelte";

	let { children }: { children: Snippet } = $props();

	const tabs = [
		{ label: "Config", href: "/settings/config" },
		{ label: "System", href: "/settings/system" },
	];

	function isActive(href: string): boolean {
		return $page.url.pathname === href || $page.url.pathname.startsWith(href + "/");
	}
</script>

<div class="space-y-(--ii-space-section-gap) p-(--ii-space-page-gutter)">
	<PageHeader title="Settings" />

	<nav class="flex gap-1 rounded-lg border border-(--ii-border) bg-(--ii-surface-alt) p-1" aria-label="Settings sections">
		{#each tabs as tab (tab.href)}
			<a
				href={tab.href}
				class="rounded-md px-4 py-2 text-sm font-medium transition-colors {isActive(tab.href)
					? 'bg-(--ii-brand-primary) text-white'
					: 'text-(--ii-text-secondary) hover:bg-(--ii-surface) hover:text-(--ii-text-primary)'}"
			>
				{tab.label}
			</a>
		{/each}
	</nav>

	{@render children()}
</div>
