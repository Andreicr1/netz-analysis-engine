<!--
  Tenant Health — per-tenant health view.
  Tenant-scoped health endpoints are not yet available from the backend.
  This page shows an explicit "not available" state rather than silent empty state.
  When the backend provides /admin/tenants/{orgId}/health, connect data here.
-->
<script lang="ts">
	import { SectionCard, MetricCard } from "@netz/ui";
	import { page } from "$app/state";

	const orgId = $derived(page.params.orgId);
	const tenant = $derived(page.data.tenant);
	const tenantName = $derived(tenant?.org_name ?? orgId);
</script>

<div class="space-y-6 p-6">
	<div class="space-y-2">
		<p class="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--netz-text-muted)]">Tenant health</p>
		<h2 class="text-2xl font-bold text-[var(--netz-text-primary)]">Health for {tenantName}</h2>
		<p class="max-w-3xl text-sm text-[var(--netz-text-secondary)]">
			Tenant-scoped health monitoring. Use the global health dashboard for system-wide worker and service status.
		</p>
	</div>

	<!-- Explicit not-available state — never silent empty state -->
	<div
		class="rounded-xl border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] px-6 py-8 text-center"
		role="status"
		aria-label="Tenant health not available"
	>
		<div class="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-[var(--netz-border)] bg-[var(--netz-surface)]">
			<span class="text-lg text-[var(--netz-text-muted)]" aria-hidden="true">&#x26A0;</span>
		</div>
		<p class="text-sm font-semibold text-[var(--netz-text-primary)]">Tenant health not available</p>
		<p class="mt-2 max-w-md mx-auto text-sm text-[var(--netz-text-secondary)]">
			The <code class="font-mono text-xs">/admin/tenants/{'{orgId}'}/health</code> endpoint is not yet implemented.
			This page will display per-tenant service status, worker assignment, and pipeline metrics once the backend contract is in place.
		</p>
		<div class="mt-4">
			<a
				href="/health"
				class="inline-flex h-8 items-center justify-center rounded-md border border-[var(--netz-border)] bg-transparent px-3 text-xs font-medium text-[var(--netz-text-primary)] transition-colors hover:bg-[var(--netz-surface)]"
			>
				View global health dashboard
			</a>
		</div>
	</div>

	<!-- Placeholder metrics — will be hydrated once endpoint is available -->
	<SectionCard title="Planned metrics">
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
			<MetricCard label="Pipeline queue depth" value="—" />
			<MetricCard label="Worker errors (24h)" value="—" />
			<MetricCard label="Last pipeline run" value="—" />
		</div>
		<p class="mt-3 text-xs text-[var(--netz-text-muted)]">
			These metrics are placeholders. They will be populated when the tenant-scoped health API is available.
		</p>
	</SectionCard>

	<SectionCard title="What will be here">
		<ul class="list-disc space-y-2 pl-5 text-sm text-[var(--netz-text-secondary)]">
			<li>Per-tenant pipeline queue depth and error rate.</li>
			<li>Worker assignments scoped to this tenant's data.</li>
			<li>Last successful pipeline run timestamp and freshness indicator.</li>
			<li>Tenant-specific alert history.</li>
		</ul>
	</SectionCard>
</div>
