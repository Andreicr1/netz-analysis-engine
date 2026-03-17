<!--
  Tenant card — compact card with org info. Clickable — navigates to detail.
-->
<script lang="ts">
	import { StatusBadge } from "@netz/ui";

	let {
		tenant,
	}: {
		tenant: {
			organization_id: string;
			org_name: string;
			org_slug: string;
			vertical: string;
			config_count: number;
			asset_count: number;
		};
	} = $props();
</script>

<a
	href="/tenants/{tenant.organization_id}"
	class="block rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4 transition-colors hover:border-[var(--netz-brand-primary)]"
>
	<div class="mb-2 flex items-center justify-between">
		<span class="font-medium text-[var(--netz-text-primary)]">{tenant.org_name}</span>
		<StatusBadge
			status={tenant.vertical === "liquid_funds" ? "info" : "accent"}
			label={tenant.vertical.replace("_", " ")}
		/>
	</div>
	<p class="mb-3 text-xs text-[var(--netz-text-muted)]">{tenant.org_slug}</p>
	<div class="flex gap-4 text-xs text-[var(--netz-text-secondary)]">
		<span>{tenant.config_count} configs</span>
		<span>{tenant.asset_count} assets</span>
	</div>
</a>
