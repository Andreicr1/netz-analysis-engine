<!--
  Tenant list — grid of TenantCards with Create button.
-->
<script lang="ts">
	import { SectionCard, EmptyState, Dialog, Button, ActionButton, FormField, Input, Select, PageHeader } from "@netz/ui";
	import type { PageData } from "./$types";
	import TenantCard from "$lib/components/TenantCard.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { goto } from "$app/navigation";

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

	const planOptions = [
		{ value: "standard", label: "Standard" },
		{ value: "professional", label: "Professional" },
		{ value: "enterprise", label: "Enterprise" },
	];

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
	<PageHeader title="Tenants">
		{#snippet actions()}
			<Button onclick={onOpen}>Create Tenant</Button>
		{/snippet}
	</PageHeader>

	{#if data.tenants.length > 0}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each data.tenants as tenant}
				<TenantCard {tenant} />
			{/each}
		</div>
	{:else}
		<EmptyState title="No tenants" message="Create one to get started." actionLabel="Create Tenant" onAction={onOpen} />
	{/if}

	<Dialog bind:open={showCreate}>
		<h2 class="mb-4 text-lg font-semibold text-(--netz-text-primary)">
			Create Tenant
		</h2>
		<div class="space-y-4">
			<FormField label="Organization Name" required error={touched.name ? errors.name : null}>
				<Input
					value={form.name}
					oninput={(e) => (form.name = e.currentTarget.value)}
					placeholder="Acme Capital"
					onblur={() => (touched.name = true)}
				/>
			</FormField>

			<FormField label="Slug" required error={touched.slug ? errors.slug : null} hint="URL-safe identifier">
				<Input
					value={form.slug}
					oninput={(e) => (form.slug = e.currentTarget.value)}
					placeholder="acme-capital"
					onblur={() => (touched.slug = true)}
				/>
			</FormField>

			<FormField label="Clerk Org ID" hint="Optional — link to Clerk organization">
				<Input
					value={form.clerk_org_id}
					oninput={(e) => (form.clerk_org_id = e.currentTarget.value)}
					placeholder="org_..."
				/>
			</FormField>

			<FormField label="Plan Tier">
				<Select
					value={form.plan_tier}
					onValueChange={(v) => (form.plan_tier = v)}
					options={planOptions}
					placeholder=""
				/>
			</FormField>

			{#if error}
				<p class="text-xs text-(--netz-danger)">{error}</p>
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
