<!--
  Tenant detail layout — ContextSidebar with navigation links.
  Server-routed sub-pages (NOT client-side tabs).
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { ContextSidebar } from "@netz/ui";
	import type { ContextNav } from "@netz/ui/utils";

	let { children }: { children: import("svelte").Snippet } = $props();

	const orgId = $derived($page.params.orgId);

	const contextNav: ContextNav = $derived({
		backHref: "/tenants",
		backLabel: "All Tenants",
		activeHref: $page.url.pathname,
		items: [
			{ label: "Overview", href: `/tenants/${orgId}` },
			{ label: "Branding", href: `/tenants/${orgId}/branding` },
			{ label: "Config", href: `/tenants/${orgId}/config` },
			{ label: "Prompts", href: `/tenants/${orgId}/prompts` },
		],
	});
</script>

<div class="flex h-full">
	<ContextSidebar nav={contextNav} />
	<div class="flex-1 overflow-auto">
		{@render children()}
	</div>
</div>
