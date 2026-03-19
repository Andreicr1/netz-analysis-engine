<!--
  Tenant Overview — org info, edit metadata, re-seed, config count.
-->
<script lang="ts">
	import { SectionCard, MetricCard, ActionButton, FormField, Button, Input, Select, PageHeader } from "@netz/ui";
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

	const planOptions = [
		{ value: "standard", label: "Standard" },
		{ value: "professional", label: "Professional" },
		{ value: "enterprise", label: "Enterprise" },
	];

	const statusOptions = [
		{ value: "active", label: "Active" },
		{ value: "suspended", label: "Suspended" },
		{ value: "archived", label: "Archived" },
	];

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
	<PageHeader title="Overview">
		{#snippet actions()}
			{#if !editing}
				<Button variant="outline" size="sm" onclick={startEdit}>Edit tenant details</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="space-y-6">
		{#if editing}
			<SectionCard title="Edit tenant">
				<div class="space-y-4">
					<FormField label="Name" required>
						<Input
							value={editForm.name}
							oninput={(e) => (editForm.name = e.currentTarget.value)}
						/>
					</FormField>
					<FormField label="Plan Tier">
						<Select
							value={editForm.plan_tier}
							onValueChange={(v) => (editForm.plan_tier = v)}
							options={planOptions}
							placeholder=""
						/>
					</FormField>
					<FormField label="Status">
						<Select
							value={editForm.status}
							onValueChange={(v) => (editForm.status = v)}
							options={statusOptions}
							placeholder=""
						/>
					</FormField>
					{#if editError}
						<p class="text-xs text-(--netz-danger)">{editError}</p>
					{/if}
					<div class="flex justify-end gap-3">
						<Button variant="outline" onclick={cancelEdit} disabled={saving}>Cancel</Button>
						<ActionButton onclick={saveEdit} loading={saving} loadingText="Saving..." disabled={!editForm.name}>
							Save for {tenantName}
						</ActionButton>
					</div>
				</div>
			</SectionCard>
		{:else}
			<SectionCard title="Details">
				<div class="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
					<div>
						<span class="text-(--netz-text-muted)">Organization ID</span>
						<p class="font-mono text-(--netz-text-primary)">
							{tenant?.organization_id ?? "\u2014"}
						</p>
					</div>
					<div>
						<span class="text-(--netz-text-muted)">Slug</span>
						<p class="text-(--netz-text-primary)">{tenant?.org_slug ?? "\u2014"}</p>
					</div>
					<div>
						<span class="text-(--netz-text-muted)">Plan</span>
						<p class="text-(--netz-text-primary)">{tenant?.plan_tier ?? "\u2014"}</p>
					</div>
					<div>
						<span class="text-(--netz-text-muted)">Status</span>
						<p class="text-(--netz-text-primary)">{tenant?.status ?? "active"}</p>
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
					class="rounded-xl border border-(--netz-border) bg-(--netz-surface) p-4 transition-colors hover:border-(--netz-brand-primary)"
				>
					<p class="text-sm font-semibold text-(--netz-text-primary)">Setup center</p>
					<p class="mt-2 text-sm text-(--netz-text-secondary)">
						Move seeding, replacement warnings, and one-time setup actions into a single place.
					</p>
				</a>
				<div class="rounded-xl border border-(--netz-border) bg-(--netz-surface) p-4">
					<p class="text-sm font-semibold text-(--netz-text-primary)">Scoped workspaces</p>
					<p class="mt-2 text-sm text-(--netz-text-secondary)">
						Config and prompt routes below are the tenant-scoped index pages. Open the vertical workspace from there.
					</p>
					<div class="mt-4 flex flex-wrap gap-2">
						<a href="/tenants/{data.orgId}/config" class="text-sm text-(--netz-brand-secondary) hover:underline">
							Config
						</a>
						<a href="/tenants/{data.orgId}/prompts" class="text-sm text-(--netz-brand-secondary) hover:underline">
							Prompts
						</a>
						<a href="/tenants/{data.orgId}/branding" class="text-sm text-(--netz-brand-secondary) hover:underline">
							Branding
						</a>
					</div>
				</div>
			</div>
		</SectionCard>
	</div>
</div>
