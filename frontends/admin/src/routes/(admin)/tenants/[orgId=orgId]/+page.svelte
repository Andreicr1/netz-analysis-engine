<!--
  Tenant Overview — org info, edit metadata, re-seed, config count.
-->
<script lang="ts">
	import { SectionCard, MetricCard, ActionButton, FormField, Button } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import type { ConfigListItem, TenantAsset } from "$lib/types";

type TenantOverview = {
  organization_id: string;
  org_name: string;
  org_slug: string;
  plan_tier?: string | null;
  status?: string | null;
  configs: ConfigListItem[];
  assets: TenantAsset[];
};

type PageData = {
  tenant: TenantOverview | null;
  orgId: string;
  token: string;
};

	let { data }: { data: PageData } = $props();
	const tenant = $derived(data.tenant);
	const tenantName = $derived(tenant?.org_name ?? "this tenant");
	const configCount = $derived(tenant?.configs?.length ?? 0);
	const assetCount = $derived(tenant?.assets?.length ?? 0);

	// Edit state
	let editing = $state(false);
	let editForm = $state({ name: "", plan_tier: "standard", status: "active" });
	let saving = $state(false);
	let editError = $state<string | null>(null);

	function startEdit() {
		editForm = {
			name: tenant?.org_name ?? "",
			plan_tier: tenant?.plan_tier ?? "standard",
			status: tenant?.status ?? "active",
		};
		editError = null;
		editing = true;
	}

	function cancelEdit() {
		editing = false;
		editError = null;
	}

	async function saveEdit() {
		saving = true;
		editError = null;
		try {
			const api = createClientApiClient(() => Promise.resolve(data.token));
			await api.patch(`/admin/tenants/${data.orgId}`, editForm);
			editing = false;
			await invalidateAll();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Save failed";
		} finally {
			saving = false;
		}
	}
</script>

<div class="space-y-6 p-6">
	<div class="flex flex-col gap-3 rounded-2xl border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4 md:flex-row md:items-center md:justify-between">
		<div class="space-y-1">
			<p class="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--netz-text-muted)]">
				Tenant workspace
			</p>
			<h2 class="text-xl font-bold text-[var(--netz-text-primary)]">{tenant?.org_name ?? "Tenant"}</h2>
			<p class="text-sm text-[var(--netz-text-secondary)]">
				{tenant?.organization_id ?? data.orgId}
			</p>
		</div>
		{#if !editing}
			<Button variant="outline" size="sm" onclick={startEdit}>Edit tenant details</Button>
		{/if}
	</div>

	{#if editing}
		<SectionCard title="Edit tenant">
			<div class="space-y-4">
				<FormField label="Name" required>
					<input
						bind:value={editForm.name}
						class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
					/>
				</FormField>
				<FormField label="Plan Tier">
					<select
						bind:value={editForm.plan_tier}
						class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
					>
						<option value="standard">Standard</option>
						<option value="professional">Professional</option>
						<option value="enterprise">Enterprise</option>
					</select>
				</FormField>
				<FormField label="Status">
					<select
						bind:value={editForm.status}
						class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
					>
						<option value="active">Active</option>
						<option value="suspended">Suspended</option>
						<option value="archived">Archived</option>
					</select>
				</FormField>
				{#if editError}
					<p class="text-xs text-[var(--netz-danger)]">{editError}</p>
				{/if}
				<div class="flex justify-end gap-3">
					<Button variant="outline" onclick={cancelEdit} disabled={saving}>Cancel</Button>
					<ActionButton onclick={saveEdit} loading={saving} loadingText="Saving..." disabled={!editForm.name}>
						Save for this tenant
					</ActionButton>
				</div>
			</div>
		</SectionCard>
	{:else}
		<SectionCard title="Details">
			<div class="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
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
				<div>
					<span class="text-[var(--netz-text-muted)]">Plan</span>
					<p class="text-[var(--netz-text-primary)]">{tenant?.plan_tier ?? "\u2014"}</p>
				</div>
				<div>
					<span class="text-[var(--netz-text-muted)]">Status</span>
					<p class="text-[var(--netz-text-primary)]">{tenant?.status ?? "active"}</p>
				</div>
			</div>
		</SectionCard>
	{/if}

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<MetricCard label="Config Overrides" value={String(configCount)} />
		<MetricCard label="Assets" value={String(assetCount)} />
	</div>

	<SectionCard title="Tenant surfaces">
		<div class="grid gap-4 md:grid-cols-2">
			<a
				href="/tenants/{data.orgId}/setup"
				class="rounded-xl border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4 transition-colors hover:border-[var(--netz-brand-primary)]"
			>
				<p class="text-sm font-semibold text-[var(--netz-text-primary)]">Setup center</p>
				<p class="mt-2 text-sm text-[var(--netz-text-secondary)]">
					Move seeding, replacement warnings, and one-time setup actions into a single place.
				</p>
			</a>
			<div class="rounded-xl border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4">
				<p class="text-sm font-semibold text-[var(--netz-text-primary)]">Scoped workspaces</p>
				<p class="mt-2 text-sm text-[var(--netz-text-secondary)]">
					Config and prompt routes below are the tenant-scoped index pages. Open the vertical workspace from there.
				</p>
				<div class="mt-4 flex flex-wrap gap-2">
					<a href="/tenants/{data.orgId}/config" class="text-sm text-[var(--netz-brand-secondary)] hover:underline">
						Config
					</a>
					<a href="/tenants/{data.orgId}/prompts" class="text-sm text-[var(--netz-brand-secondary)] hover:underline">
						Prompts
					</a>
					<a href="/tenants/{data.orgId}/branding" class="text-sm text-[var(--netz-brand-secondary)] hover:underline">
						Branding
					</a>
				</div>
			</div>
		</div>
	</SectionCard>
</div>


