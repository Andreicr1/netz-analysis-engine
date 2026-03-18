<!--
  Tenant Branding — color pickers, asset upload/delete, live preview.
-->
<script lang="ts">
	import BrandingEditor from "$lib/components/BrandingEditor.svelte";
	import { SectionCard, ActionButton, ConfirmDialog, Button } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { onDestroy } from "svelte";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	const tenantName = $derived(data.tenant?.org_name ?? "this tenant");
	const tenantScope = $derived(
		data.tenant
			? `${data.tenant.org_name} (${data.tenant.organization_id})`
			: `tenant ${data.orgId}`,
	);

	// Asset upload state
	const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/x-icon"];
	const MAGIC_BYTES: Record<string, number[]> = {
		"image/png": [0x89, 0x50, 0x4e, 0x47],
		"image/jpeg": [0xff, 0xd8, 0xff],
		"image/x-icon": [0x00, 0x00, 0x01, 0x00],
	};

	let uploading = $state(false);
	let uploadError = $state<string | null>(null);
	let selectedFile = $state<File | null>(null);
	let filePreview = $state<string | null>(null);

	onDestroy(() => {
		if (filePreview) URL.revokeObjectURL(filePreview);
	});
	let assetType = $state("logo");
	let deleteTarget = $state<string | null>(null);
	let showDeleteConfirm = $state(false);

	async function validateMagicBytes(file: File): Promise<boolean> {
		const buf = await file.slice(0, 4).arrayBuffer();
		const bytes = new Uint8Array(buf);
		return ALLOWED_TYPES.some((type) => {
			const magic = MAGIC_BYTES[type];
			return magic?.every((b, i) => bytes[i] === b) ?? false;
		});
	}

	async function onFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;

		uploadError = null;

		if (!ALLOWED_TYPES.includes(file.type)) {
			uploadError = "Only PNG, JPEG, and ICO files are allowed";
			return;
		}

		const validMagic = await validateMagicBytes(file);
		if (!validMagic) {
			uploadError = "File content does not match its extension";
			return;
		}

		selectedFile = file;
		filePreview = URL.createObjectURL(file);
	}

	async function uploadAsset() {
		if (!selectedFile) return;
		uploading = true;
		uploadError = null;
		try {
			const api = createClientApiClient(() => Promise.resolve(data.token));
			const formData = new FormData();
			formData.append("file", selectedFile);
			formData.append("asset_type", assetType);
			await api.upload(`/admin/tenants/${data.orgId}/assets`, formData);
			selectedFile = null;
			if (filePreview) URL.revokeObjectURL(filePreview);
			filePreview = null;
			await invalidateAll();
		} catch (e) {
			uploadError = e instanceof Error ? e.message : "Upload failed";
		} finally {
			uploading = false;
		}
	}

	function confirmDelete(type: string) {
		deleteTarget = type;
		showDeleteConfirm = true;
	}

	async function deleteAsset() {
		if (!deleteTarget) return;
		const api = createClientApiClient(() => Promise.resolve(data.token));
		await api.delete(`/admin/tenants/${data.orgId}/assets/${deleteTarget}`);
		deleteTarget = null;
		await invalidateAll();
	}
</script>

<div class="space-y-6 p-6">
	<h2 class="text-xl font-bold text-[var(--netz-text-primary)]">Branding</h2>
	<BrandingEditor branding={data.branding} orgId={data.orgId} />

	<!-- Asset Upload -->
	<SectionCard title="Brand Assets">
		<div class="space-y-4">
			<div class="flex items-center gap-4">
				<select
					bind:value={assetType}
					class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				>
					<option value="logo">Logo</option>
					<option value="icon">Icon (Favicon)</option>
					<option value="banner">Banner</option>
				</select>
				<input
					type="file"
					accept="image/png,image/jpeg,image/x-icon"
					onchange={onFileSelect}
					class="text-sm text-[var(--netz-text-primary)]"
				/>
			</div>

			{#if filePreview}
				<div class="flex items-center gap-4">
					<img src={filePreview} alt="Preview" class="h-16 w-16 rounded border border-[var(--netz-border)] object-contain" />
					<ActionButton onclick={uploadAsset} loading={uploading} loadingText="Uploading...">
						Upload {assetType} to this tenant
					</ActionButton>
				</div>
			{/if}

			{#if uploadError}
				<p class="text-xs text-[var(--netz-danger)]">{uploadError}</p>
			{/if}

			<!-- Existing assets -->
			{#if data.tenant?.assets?.length}
				<div class="mt-4 space-y-2">
					<h3 class="text-sm font-medium text-[var(--netz-text-secondary)]">Uploaded Assets</h3>
					{#each data.tenant.assets as asset}
						<div class="flex items-center justify-between rounded border border-[var(--netz-border)] p-3">
							<span class="text-sm text-[var(--netz-text-primary)]">{asset.asset_type ?? asset.type ?? "unknown"}</span>
							<Button variant="destructive" size="sm" onclick={() => confirmDelete(asset.asset_type ?? asset.type)}>
								Delete from this tenant
							</Button>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</SectionCard>

	<ConfirmDialog
		bind:open={showDeleteConfirm}
		title={`Delete asset from ${tenantName}`}
		message={`This will permanently remove this branding asset from ${tenantScope}. Continue?`}
		confirmLabel="Delete from this tenant"
		confirmVariant="destructive"
		onConfirm={deleteAsset}
	/>
</div>
