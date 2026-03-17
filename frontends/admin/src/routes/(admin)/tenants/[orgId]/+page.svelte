<!--
  Tenant Overview — org info, config count, re-seed button.
-->
<script lang="ts">
	import { SectionCard, MetricCard } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	const tenant = $derived(data.tenant);
</script>

<div class="space-y-6 p-6">
	<h2 class="text-xl font-bold text-[var(--netz-text-primary)]">
		{tenant?.org_name ?? "Tenant"}
	</h2>

	<SectionCard title="Details">
		<div class="grid grid-cols-2 gap-4 text-sm">
			<div>
				<span class="text-[var(--netz-text-muted)]">Organization ID</span>
				<p class="font-mono text-[var(--netz-text-primary)]">
					{tenant?.organization_id ?? "\u2014"}
				</p>
			</div>
			<div>
				<span class="text-[var(--netz-text-muted)]">Slug</span>
				<p class="text-[var(--netz-text-primary)]">{tenant?.org_slug ?? "\u2014"}</p>
			</div>
		</div>
	</SectionCard>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<MetricCard label="Config Overrides" value={String(tenant?.configs?.length ?? 0)} />
		<MetricCard label="Assets" value={String(tenant?.assets?.length ?? 0)} />
	</div>

	<SectionCard title="Actions">
		<button
			class="rounded-md border border-[var(--netz-border)] px-4 py-2 text-sm text-[var(--netz-text-primary)] hover:bg-[var(--netz-surface-alt)]"
		>
			Re-seed Default Configs
		</button>
	</SectionCard>
</div>
