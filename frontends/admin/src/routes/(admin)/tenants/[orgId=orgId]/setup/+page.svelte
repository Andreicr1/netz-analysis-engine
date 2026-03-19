<script lang="ts">
	import { invalidateAll } from "$app/navigation";
	import { createClientApiClient } from "$lib/api/client";
	import { ActionButton, ConfirmDialog, MetricCard, PageHeader, SectionCard } from "@netz/ui";
	import type { TenantDetail } from "$lib/types";

type PageData = {
  tenant: TenantDetail | null;
  orgId: string;
  token: string;
};

	let { data }: { data: PageData } = $props();
	const tenant = $derived(data.tenant);
	const tenantName = $derived(tenant?.org_name ?? "this tenant");
	const tenantScope = $derived(
		tenant ? `${tenant.org_name} (${tenant.organization_id})` : `tenant ${data.orgId}`,
	);

	let showSeedConfirm = $state(false);
	let seeding = $state(false);
	let setupError = $state<string | null>(null);

	async function seedDefaults() {
		seeding = true;
		setupError = null;
		try {
			const api = createClientApiClient(() => Promise.resolve(data.token));
			await api.post(`/admin/tenants/${data.orgId}/seed`);
			await invalidateAll();
		} catch (error) {
			setupError = error instanceof Error ? error.message : "Unable to seed defaults.";
		} finally {
			seeding = false;
		}
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Setup center for {tenantName}" />
	<p class="mt-1 max-w-3xl text-sm text-(--netz-text-muted)">
		Use this page for one-time tenant bootstrap actions. Seed operations live here now so the overview page stays read-only and the replacement risk is explicit before you act.
	</p>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<MetricCard label="Config Overrides" value={String(tenant?.configs?.length ?? 0)} />
		<MetricCard label="Assets" value={String(tenant?.assets?.length ?? 0)} />
	</div>

	<SectionCard title="Replacement warning">
		<div class="space-y-3 text-sm text-(--netz-text-secondary)">
			<p>
				Seeding default configs creates missing overrides only. Existing tenant overrides are left in place.
			</p>
			<p>
				Use this page only when you are intentionally initializing a tenant or restoring baseline defaults.
			</p>
		</div>
	</SectionCard>

	<SectionCard title="What seeding does">
		<ul class="list-disc space-y-2 pl-5 text-sm text-(--netz-text-secondary)">
			<li>Creates default config overrides that are missing for this tenant.</li>
			<li>Does not overwrite existing overrides.</li>
			<li>Returns the tenant to a known baseline before further config work.</li>
		</ul>
	</SectionCard>

	{#if setupError}
		<div class="rounded-xl border border-(--netz-danger)/30 bg-(--netz-danger)/5 px-4 py-3 text-sm text-(--netz-danger)" role="alert">
			{setupError}
		</div>
	{/if}

	<SectionCard title="Seed defaults">
		<div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
			<div class="space-y-1">
				<p class="text-sm font-semibold text-(--netz-text-primary)">Initialize {tenantName}</p>
				<p class="text-sm text-(--netz-text-secondary)">
					You will be asked to confirm that you understand the seed action only fills in missing defaults for {tenantScope}.
				</p>
			</div>
			<div class="flex items-center gap-3">
				<a href="/tenants/{data.orgId}" class="inline-flex h-8 items-center justify-center rounded-md border border-(--netz-border) bg-transparent px-3 text-xs font-medium text-(--netz-text-primary) transition-colors hover:bg-(--netz-surface-alt)">Back to overview</a>
				<ActionButton onclick={() => (showSeedConfirm = true)} loading={seeding} loadingText="Seeding..." size="sm">
					Seed defaults for this tenant
				</ActionButton>
			</div>
		</div>
	</SectionCard>

	<ConfirmDialog
		bind:open={showSeedConfirm}
		title={`Seed default configs for ${tenantName}`}
		message={`This will create missing default config overrides for ${tenantScope}. Existing overrides will not be replaced.`}
		confirmLabel="Seed for this tenant"
		onConfirm={seedDefaults}
	/>
</div>




