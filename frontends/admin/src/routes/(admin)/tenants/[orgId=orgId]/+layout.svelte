<!--
  Tenant detail layout — ContextSidebar via AppLayout's contextNav prop.
  Server-routed sub-pages (NOT client-side tabs).
-->
<script lang="ts">
	import { page } from "$app/state";
	import { useContextNav } from "$lib/state/context-nav.svelte";

	let { children }: { children: import("svelte").Snippet } = $props();
	const nav = useContextNav();

	const orgId = $derived(page.params.orgId);

	$effect(() => {
		const id = orgId;
		const pathname = page.url.pathname;

		nav.current = {
			backHref: "/tenants",
			backLabel: "All Tenants",
			activeHref: pathname,
			items: [
				{ label: "Overview", href: `/tenants/${id}` },
				{ label: "Branding", href: `/tenants/${id}/branding` },
				{ label: "Config", href: `/tenants/${id}/config` },
				{ label: "Prompts", href: `/tenants/${id}/prompts` },
			],
		};

		return () => {
			nav.current = null;
		};
	});
</script>

<div class="flex-1 overflow-auto">
	{@render children()}
</div>
