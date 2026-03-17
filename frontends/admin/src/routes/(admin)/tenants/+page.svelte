<!--
  Tenant list — grid of TenantCards with Create button.
-->
<script lang="ts">
	import { SectionCard, EmptyState, Dialog, Button, ActionButton, FormField } from "@netz/ui";
	import type { PageData } from "./$types";
	import TenantCard from "$lib/components/TenantCard.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { goto, invalidateAll } from "$app/navigation";

	let { data }: { data: PageData } = $props();
	let showCreate = $state(false);
	let form = $state({ name: "", slug: "", clerk_org_id: "", plan_tier: "standard" });
	let creating = $state(false);
	let error = $state<string | null>(null);
	let touched = $state<Record<string, boolean>>({});

	const slugRegex = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
	let errors = $derived({
		name: !form.name ? "Required" : null,
		slug: !form.slug ? "Required" : !slugRegex.test(form.slug) ? "Lowercase alphanumeric + hyphens only" : null,
	});
	let canSubmit = $derived(!errors.name && !errors.slug && !creating);

	function resetForm() {
		form = { name: "", slug: "", clerk_org_id: "", plan_tier: "standard" };
		touched = {};
		error = null;
	}

	function onOpen() {
		resetForm();
		showCreate = true;
	}

	async function createTenant() {
		if (!canSubmit) return;
		creating = true;
		error = null;
		try {
			const api = createClientApiClient(() => Promise.resolve(data.token));
			const tenant = await api.post<{ organization_id: string }>("/admin/tenants/", {
				name: form.name,
				slug: form.slug,
				clerk_org_id: form.clerk_org_id || undefined,
				plan_tier: form.plan_tier,
			});
			showCreate = false;
			await goto(`/tenants/${tenant.organization_id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to create tenant";
		} finally {
			creating = false;
		}
	}
</script>

<div class="space-y-6 p-6">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">Tenants</h1>
		<Button onclick={onOpen}>Create Tenant</Button>
	</div>

	{#if data.tenants.length > 0}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each data.tenants as tenant}
				<TenantCard {tenant} />
			{/each}
		</div>
	{:else}
		<SectionCard title="Tenants">
			<EmptyState message="No tenants found. Create one to get started." />
		</SectionCard>
	{/if}

	<Dialog bind:open={showCreate}>
		<h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">
			Create Tenant
		</h2>
		<div class="space-y-4">
			<FormField label="Organization Name" required error={touched.name ? errors.name : null}>
				<input
					bind:value={form.name}
					placeholder="Acme Capital"
					onblur={() => (touched.name = true)}
					class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
				/>
			</FormField>

			<FormField label="Slug" required error={touched.slug ? errors.slug : null} hint="URL-safe identifier">
				<input
					bind:value={form.slug}
					placeholder="acme-capital"
					onblur={() => (touched.slug = true)}
					class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
				/>
			</FormField>

			<FormField label="Clerk Org ID" hint="Optional — link to Clerk organization">
				<input
					bind:value={form.clerk_org_id}
					placeholder="org_..."
					class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
				/>
			</FormField>

			<FormField label="Plan Tier">
				<select
					bind:value={form.plan_tier}
					class="flex h-9 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
				>
					<option value="standard">Standard</option>
					<option value="professional">Professional</option>
					<option value="enterprise">Enterprise</option>
				</select>
			</FormField>

			{#if error}
				<p class="text-xs text-[var(--netz-danger)]">{error}</p>
			{/if}

			<div class="flex justify-end gap-3">
				<Button variant="outline" onclick={() => (showCreate = false)} disabled={creating}>
					Cancel
				</Button>
				<ActionButton onclick={createTenant} loading={creating} loadingText="Creating..." disabled={!canSubmit}>
					Create
				</ActionButton>
			</div>
		</div>
	</Dialog>
</div>
