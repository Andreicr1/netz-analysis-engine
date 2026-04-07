<!--
  Settings layout — internal nav for Config and System sub-pages.
  Uses PageTabs in controlled mode with goto() for route-based tab switching.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { goto } from "$app/navigation";
	import { PageHeader, PageTabs } from "@investintell/ui";
	import type { Snippet } from "svelte";

	let { children: pageContent }: { children: Snippet } = $props();

	const tabs = [
		{ value: "/settings/config", label: "Config" },
		{ value: "/settings/system", label: "System" },
	];

	const activeTab = $derived(
		tabs.find((t) => $page.url.pathname.startsWith(t.value))?.value ?? "/settings/config",
	);

	function handleTabChange(value: string) {
		goto(value);
	}
</script>

<div class="space-y-(--ii-space-section-gap) p-(--ii-space-page-gutter)">
	<PageHeader title="Settings" />

	<PageTabs {tabs} active={activeTab} onChange={handleTabChange}>
		{#snippet children(_tab)}
			{@render pageContent()}
		{/snippet}
	</PageTabs>
</div>
