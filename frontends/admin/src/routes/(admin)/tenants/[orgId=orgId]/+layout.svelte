<!--
  Tenant detail layout — ContextSidebar via AppLayout's contextNav prop.
  Server-routed sub-pages (NOT client-side tabs).
-->
<script lang="ts">
	import { page } from "$app/state";
	import { useContextNav } from "$lib/state/context-nav.svelte";
	import { EntityContextHeader } from "@netz/ui";

	let { children }: { children: import("svelte").Snippet } = $props();
	const nav = useContextNav();

	const tenant = $derived(page.data.tenant);
	const orgId = $derived(page.params.orgId);
	const tenantTitle = $derived(tenant?.org_name ?? "Tenant");
	const tenantSlug = $derived(tenant?.org_slug ?? null);
	const tenantPlan = $derived(tenant?.plan_tier ?? null);
	const tenantStatus = $derived(tenant?.status ?? null);

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
				{ label: "Setup", href: `/tenants/${id}/setup` },
			],
		};

		return () => {
			nav.current = null;
		};
	});
</script>

<div class="flex-1 overflow-auto">
	<EntityContextHeader
		title={tenantTitle}
		orgId={tenant?.organization_id ?? orgId}
		slug={tenantSlug}
		planTier={tenantPlan}
		status={tenantStatus}
	/>
	{@render children()}
</div>
