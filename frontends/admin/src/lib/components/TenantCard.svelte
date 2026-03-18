<!--
  Tenant card — compact card with org info. Clickable — navigates to detail.
-->
<script lang="ts">

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

	const orgLabel = $derived(`Org ID: ${tenant.organization_id}`);
	const verticalLabel = $derived(tenant.vertical.replace("_", " "));
</script>

<a
	href="/tenants/{tenant.organization_id}"
	class="block rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4 transition-colors hover:border-[var(--netz-brand-primary)]"
>
	<div class="mb-2 flex items-start justify-between gap-3">
		<div class="min-w-0">
			<p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--netz-text-muted)]">
				Tenant
			</p>
			<span class="block truncate font-medium text-[var(--netz-text-primary)]">{tenant.org_name}</span>
		</div>
		<span
			class="inline-flex items-center rounded-full border border-[var(--netz-border)] bg-[var(--netz-surface)] px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--netz-text-secondary)]"
		>
			{verticalLabel}
		</span>
	</div>
	<div class="mb-3 space-y-1 text-xs text-[var(--netz-text-muted)]">
		<p class="font-mono">{orgLabel}</p>
		<p>Slug: {tenant.org_slug}</p>
	</div>
	<div class="flex gap-4 text-xs text-[var(--netz-text-secondary)]">
		<span>{tenant.config_count} configs</span>
		<span>{tenant.asset_count} assets</span>
	</div>
</a>
