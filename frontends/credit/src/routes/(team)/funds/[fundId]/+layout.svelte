<!--
  Fund context layout — sets ContextSidebar for fund-scoped navigation.
-->
<script lang="ts">
	import { page } from "$app/state";
	import { PageHeader } from "@netz/ui";
	import { useContextNav } from "$lib/state/context-nav.svelte";
	import type { Snippet } from "svelte";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: Snippet } = $props();
	const nav = useContextNav();

	$effect(() => {
		const fundId = data.fund.id;
		const fundName = data.fund.name;
		const pathname = page.url.pathname;

		nav.current = {
			backHref: "/funds",
			backLabel: fundName,
			items: [
				{ label: "Pipeline", href: `/funds/${fundId}/pipeline` },
				{ label: "Portfolio", href: `/funds/${fundId}/portfolio` },
				{ label: "Documents", href: `/funds/${fundId}/documents` },
				{ label: "Reporting", href: `/funds/${fundId}/reporting` },
			],
			activeHref: pathname,
		};

		return () => {
			nav.current = null;
		};
	});
</script>

<PageHeader title={data.fund.name} />

<div class="flex-1 overflow-y-auto">
	{@render children()}
</div>
