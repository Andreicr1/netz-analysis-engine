<!--
  Tenant Overview — org info, edit metadata, re-seed, config count.
-->
<script lang="ts">
	import { SectionCard, MetricCard, ActionButton, ConfirmDialog, FormField, Button } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	const tenant = $derived(data.tenant);

	// Edit state
	let editing = $state(false);
	let editForm = $state({ name: "", plan_tier: "standard", status: "active" });
	let saving = $state(false);
	let editError = $state<string | null>(null);

	// Seed state
	let showSeedConfirm = $state(false);

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

	async function seedDefaults() {
		const api = createClientApiClient(() => Promise.resolve(data.token));
		await api.post(`/admin/tenants/${data.orgId}/seed`);
		await invalidateAll();
	}
</script>

<div class="space-y-6 p-6">
	<div class="flex items-center justify-between">
		<h2 class="text-xl font-bold text-[var(--netz-text-primary)]">
			{tenant?.org_name ?? "Tenant"}
		</h2>
		{#if !editing}
			<Button variant="outline" size="sm" onclick={startEdit}>Edit</Button>
		{/if}
	</div>

	{#if editing}
		<SectionCard title="Edit Tenant">
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
						Save Changes
					</ActionButton>
				</div>
			</div>
		</SectionCard>
	{:else}
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
		<MetricCard label="Config Overrides" value={String(tenant?.configs?.length ?? 0)} />
		<MetricCard label="Assets" value={String(tenant?.assets?.length ?? 0)} />
	</div>

	<SectionCard title="Actions">
		<ActionButton
			variant="outline"
			onclick={() => (showSeedConfirm = true)}
		>
			Re-seed Default Configs
		</ActionButton>
	</SectionCard>

	<ConfirmDialog
		bind:open={showSeedConfirm}
		title="Seed Default Configs"
		message="This will create default config overrides for this tenant. Existing overrides will not be affected."
		confirmLabel="Seed"
		onConfirm={seedDefaults}
	/>
</div>
