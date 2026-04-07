<!--
  Config Editor — CodeMirror JSON editor with consequence-aware save,
  inline diff view, and audit trail panel.
  Migrated from frontends/admin to @investintell/ui for reuse across verticals.
  Accepts apiBaseUrl as prop — caller provides the backend URL.
-->
<script lang="ts">
	import SectionCard from "./SectionCard.svelte";
	import ActionButton from "./ActionButton.svelte";
	import { Button } from "$lib/components/ui/button";
	import ConsequenceDialog from "./ConsequenceDialog.svelte";
	import AuditTrailPanel from "./AuditTrailPanel.svelte";
	import type {
		ConsequenceDialogPayload,
		ConsequenceDialogMetadataItem,
	} from "./ConsequenceDialog.svelte";
	import type { AuditTrailEntry } from "./AuditTrailPanel.svelte";
	import { createClientApiClient } from "../../utils/api-client.js";
	import CodeEditor from "./CodeEditor.svelte";
	import ConfigDiffView from "./ConfigDiffView.svelte";
	import type { ConfigDiffOut } from "./ConfigDiffView.svelte";

	let {
		vertical,
		configType,
		token,
		apiBaseUrl: _apiBaseUrl,
		orgId,
		tenantName,
	}: {
		vertical: string;
		configType: string;
		token: string;
		apiBaseUrl: string;
		orgId?: string;
		tenantName?: string;
	} = $props();
	const apiBaseUrl = _apiBaseUrl; // one-time snapshot

	const scopeLabel = $derived(
		orgId && tenantName
			? `${tenantName} (${orgId})`
			: orgId
				? orgId
				: "ALL tenants",
	);

	let content = $state("{}");
	let version = $state(0);
	let isDefault = $state(true);
	let saveError = $state<string | null>(null);
	let saveMessage = $state<string | null>(null);
	let saving = $state(false);
	let loading = $state(true);

	// Diff state
	let diff = $state<ConfigDiffOut | null>(null);
	let diffLoading = $state(false);
	let diffError = $state<string | null>(null);

	// Consequence dialog state
	let showSaveDialog = $state(false);
	let showDefaultDialog = $state(false);
	let showDeleteConfirm = $state(false);

	// Audit trail state
	let auditEntries = $state<AuditTrailEntry[]>([]);

	const api = createClientApiClient(apiBaseUrl, () => Promise.resolve(token));

	// ── Derived: diff metadata for ConsequenceDialog ────────────────────────

	const saveMetadata = $derived<ConsequenceDialogMetadataItem[]>([
		{ label: "Vertical", value: vertical },
		{ label: "Config type", value: configType },
		{ label: "Scope", value: scopeLabel, emphasis: true },
		...(diff
			? [
					{
						label: "Changed keys",
						value:
							diff.changed_keys.length > 0
								? diff.changed_keys.join(", ")
								: "No keys changed",
					},
					{
						label: "Tenants affected",
						value: String(diff.tenant_count_affected),
						emphasis: diff.tenant_count_affected > 1,
					},
				]
			: []),
	]);

	const defaultMetadata = $derived<ConsequenceDialogMetadataItem[]>([
		{ label: "Vertical", value: vertical },
		{ label: "Config type", value: configType },
		{
			label: "Scope",
			value: "ALL tenants without overrides",
			emphasis: true,
		},
	]);

	// ── Loaders ─────────────────────────────────────────────────────────────

	async function loadConfig() {
		loading = true;
		saveError = null;
		saveMessage = null;
		try {
			const params = orgId ? `?org_id=${orgId}` : "";
			const result = await api.get<{
				config: Record<string, unknown>;
				vertical: string;
				config_type: string;
				version?: number;
				is_default?: boolean;
			}>(`/admin/configs/${vertical}/${configType}${params}`);
			content = JSON.stringify(result.config, null, 2);
			version = result.version ?? 0;
			isDefault = result.is_default ?? true;
		} catch (e) {
			saveError = "Failed to load config";
		} finally {
			loading = false;
		}
	}

	async function loadDiff() {
		if (!orgId) return;
		diffLoading = true;
		diffError = null;
		try {
			diff = await api.get<ConfigDiffOut>(
				`/admin/configs/${vertical}/${configType}/diff`,
				{ org_id: orgId },
			);
		} catch (e: unknown) {
			diffError = e instanceof Error ? e.message : "Failed to load diff";
		} finally {
			diffLoading = false;
		}
	}

	async function loadAuditTrail() {
		try {
			const result = await api.get<{ events: Array<{
				id: string;
				actor_id: string;
				actor_roles: string[];
				action: string;
				entity_type: string;
				entity_id: string;
				created_at: string;
				before_state: Record<string, unknown> | null;
				after_state: Record<string, unknown> | null;
			}> }>(`/admin/audit`, {
				entity_type: "Config",
				action: "UPDATE",
				...(orgId ? { organization_id: orgId } : {}),
			});
			auditEntries = result.events.map((ev) => ({
				id: ev.id,
				actor: ev.actor_id,
				actorCapacity: ev.actor_roles.join(", ") || undefined,
				timestamp: ev.created_at,
				action: `${ev.action} — ${ev.entity_type}`,
				scope: `${vertical}/${configType}`,
				outcome: ev.after_state ? "Applied" : "Reverted",
				status: "success" as const,
				immutable: true,
				sourceSystem: "config-editor",
			}));
		} catch {
			// Audit trail is optional — failing silently is acceptable
		}
	}

	// ── Mutations ────────────────────────────────────────────────────────────

	async function save(_payload: ConsequenceDialogPayload) {
		if (!orgId) return;
		saving = true;
		saveError = null;
		saveMessage = null;
		try {
			const parsed = JSON.parse(content);
			await api.put(
				`/admin/configs/${vertical}/${configType}?org_id=${orgId}`,
				parsed,
				{ "If-Match": String(version) },
			);
			saveMessage = "Saved successfully";
			setTimeout(() => (saveMessage = null), 3000);
			await Promise.allSettled([loadConfig(), loadDiff(), loadAuditTrail()]);
		} catch (e: unknown) {
			if (e instanceof Error) {
				if (e.message.includes("409") || e.message.includes("modified")) {
					saveError = "Config was modified by another user. Reloading...";
					setTimeout(() => loadConfig(), 1500);
				} else if (e.message.includes("428")) {
					saveError = "Please reload to get current version";
				} else {
					saveError = e.message;
				}
			} else {
				saveError = "Save failed";
			}
			throw e; // Let ConsequenceDialog stay open on failure
		} finally {
			saving = false;
		}
	}

	async function deleteOverride() {
		if (!orgId) return;
		try {
			await api.delete(`/admin/configs/${vertical}/${configType}?org_id=${orgId}`);
			saveMessage = "Override deleted — reverted to default";
			setTimeout(() => (saveMessage = null), 3000);
			await Promise.allSettled([loadConfig(), loadDiff(), loadAuditTrail()]);
		} catch (e) {
			saveError = e instanceof Error ? e.message : "Delete failed";
		}
	}

	async function updateDefault(_payload: ConsequenceDialogPayload) {
		try {
			const parsed = JSON.parse(content);
			await api.put(`/admin/configs/defaults/${vertical}/${configType}`, parsed);
			saveMessage = "Default updated";
			setTimeout(() => (saveMessage = null), 3000);
			await Promise.allSettled([loadDiff(), loadAuditTrail()]);
		} catch (e) {
			saveError = e instanceof Error ? e.message : "Update default failed";
			throw e;
		}
	}

	// ── Effects ──────────────────────────────────────────────────────────────

	$effect(() => {
		const _v = vertical;
		const _c = configType;
		void loadConfig();
		void loadDiff();
		void loadAuditTrail();
	});
</script>

<SectionCard title="{configType} — {isDefault ? 'Default' : `Override (v${version})`}">
	{#if loading}
		<p class="text-sm text-(--ii-text-muted)">Loading...</p>
	{:else}
		<div class="space-y-4">
			<!-- CodeMirror JSON editor (replaces textarea) -->
			<CodeEditor
				bind:value={content}
				schema={{}}
				ariaLabel="{configType} config JSON editor"
			/>

			{#if saveError}
				<p role="alert" class="text-xs text-(--ii-danger)">{saveError}</p>
			{/if}
			{#if saveMessage}
				<p class="text-xs text-(--ii-brand-primary)">{saveMessage}</p>
			{/if}

			<div class="flex items-center justify-between">
				<div class="flex gap-2">
					{#if !isDefault}
						<Button
							variant="destructive"
							size="sm"
							onclick={() => (showDeleteConfirm = true)}
						>
							Revert to Default
						</Button>
					{/if}
					<Button
						variant="ghost"
						size="sm"
						onclick={() => (showDefaultDialog = true)}
					>
						Update Default for ALL tenants
					</Button>
				</div>
				<div class="flex gap-2">
					<Button variant="outline" onclick={() => void loadConfig()}>
						Reset
					</Button>
					{#if orgId}
						<ActionButton
							onclick={() => (showSaveDialog = true)}
							loading={saving}
							loadingText="Saving..."
						>
							Save Override for {tenantName ?? "this tenant"}
						</ActionButton>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</SectionCard>

<!-- Inline diff view (shown when orgId is available) -->
{#if orgId && diff}
	<ConfigDiffView {diff} />
{:else if orgId && diffLoading}
	<SectionCard title="Diff — {configType}">
		<p class="text-sm text-(--ii-text-muted)">Loading diff...</p>
	</SectionCard>
{:else if orgId && diffError}
	<SectionCard title="Diff — {configType}">
		<p class="text-sm text-(--ii-danger)">{diffError}</p>
	</SectionCard>
{/if}

<!-- Audit trail panel -->
<AuditTrailPanel
	title="Config audit trail"
	description="Record of consequential config changes for {vertical}/{configType}."
	entries={auditEntries}
/>

<!-- Save override consequence dialog -->
<ConsequenceDialog
	bind:open={showSaveDialog}
	title="Save Config Override"
	impactSummary="You are about to save a config override for {scopeLabel}. Review the changes below before confirming."
	scopeText="{configType} override for {scopeLabel}"
	destructive={false}
	requireRationale={true}
	rationaleLabel="Reason for change"
	rationalePlaceholder="Describe the operational or policy basis for this config change."
	metadata={saveMetadata}
	onConfirm={save}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm">
			<li>The override will take effect immediately for {scopeLabel}</li>
			{#if diff && diff.changed_keys.length > 0}
				<li>
					{diff.changed_keys.length} propert{diff.changed_keys.length === 1 ? "y" : "ies"} will be changed: {diff.changed_keys.join(", ")}
				</li>
			{/if}
			{#if diff && diff.tenant_count_affected > 1}
				<li class="font-medium text-(--ii-warning)">
					This will affect {diff.tenant_count_affected} tenants
				</li>
			{/if}
		</ul>
	{/snippet}
</ConsequenceDialog>

<!-- Update default consequence dialog -->
<ConsequenceDialog
	bind:open={showDefaultDialog}
	title="Update Global Default — affects ALL tenants"
	impactSummary="This will update the global default {configType} config. Every tenant using the default will receive this change immediately."
	scopeText="Global default — applies to all tenants without overrides"
	destructive={true}
	requireRationale={true}
	rationaleLabel="Reason for global default change"
	rationalePlaceholder="Describe the operational or policy basis for changing the global default."
	typedConfirmationText="UPDATE DEFAULT"
	typedConfirmationLabel="Type UPDATE DEFAULT to confirm"
	metadata={defaultMetadata}
	onConfirm={updateDefault}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm">
			<li class="font-medium text-(--ii-danger)">
				ALL tenants without overrides will be affected immediately
			</li>
			<li>This change cannot be undone automatically — a new default must be set to revert</li>
			<li>Tenants with overrides will not be affected</li>
		</ul>
	{/snippet}
</ConsequenceDialog>

<!-- Delete/revert consequence dialog (using ConsequenceDialog for consistency) -->
<ConsequenceDialog
	bind:open={showDeleteConfirm}
	title="Revert to Default"
	impactSummary="This will delete the config override for {scopeLabel} and revert to the global default."
	scopeText="{configType} override for {scopeLabel}"
	destructive={true}
	requireRationale={false}
	confirmLabel="Revert for {tenantName ?? 'this tenant'}"
	onConfirm={deleteOverride}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm">
			<li>The override for {scopeLabel} will be permanently deleted</li>
			<li>The tenant will revert to the global default immediately</li>
		</ul>
	{/snippet}
</ConsequenceDialog>
