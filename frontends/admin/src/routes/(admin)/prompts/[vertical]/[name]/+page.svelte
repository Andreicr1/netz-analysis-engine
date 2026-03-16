<!--
  Prompt editor — split pane with textarea + live preview.
  Syntax validation, save, revert, version history.
-->
<script lang="ts">
	import { PageHeader, Button, Badge, Tabs } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";

	let { data }: { data: PageData } = $props();

	interface PromptData {
		content: string;
		source_level: string;
		version: number | null;
	}

	interface VersionInfo {
		id: string;
		version: number;
		content: string;
		updated_by: string;
		created_at: string;
	}

	let prompt = $state(data.prompt as PromptData | null);
	let editContent = $state(prompt?.content ?? "");
	let previewHtml = $state("");
	let syntaxValid = $state<boolean | null>(null);
	let syntaxErrors = $state<string[]>([]);
	let saving = $state(false);
	let previewing = $state(false);
	let activeTab = $state("editor");
	let debounceTimer: ReturnType<typeof setTimeout>;

	const tabs = [
		{ id: "editor", label: "Editor" },
		{ id: "history", label: "Version History" },
	];

	function sourceBadgeText(source: string): string {
		switch (source) {
			case "org": return "Editing Org Override";
			case "global": return "Editing Global Override";
			default: return "Filesystem Template (read-only)";
		}
	}

	async function handleValidate() {
		try {
			const api = createClientApiClient(async () => data.token);
			const result = await api.post<{ valid: boolean; errors: string[] }>(
				`/admin/prompts/${data.vertical}/${data.templateName}/validate`,
				{ content: editContent }
			);
			syntaxValid = result.valid;
			syntaxErrors = result.errors;
		} catch {
			syntaxValid = null;
		}
	}

	async function handlePreview() {
		previewing = true;
		try {
			const api = createClientApiClient(async () => data.token);
			const result = await api.post<{ rendered: string; errors: string[] | null }>(
				`/admin/prompts/${data.vertical}/${data.templateName}/preview`,
				{ content: editContent, sample_data: { deal_name: "Sample Corp", name: "John Doe", fund_name: "Growth Fund I" } }
			);
			previewHtml = result.rendered || result.errors?.join("\n") || "";
		} catch {
			previewHtml = "Preview failed";
		} finally {
			previewing = false;
		}
	}

	function handleInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			handleValidate();
			handlePreview();
		}, 500);
	}

	async function handleSave() {
		saving = true;
		try {
			const api = createClientApiClient(async () => data.token);
			await api.put(`/admin/prompts/${data.vertical}/${data.templateName}`, {
				content: editContent,
			});
			await invalidateAll();
		} catch (e) {
			console.error("Save failed:", e);
		} finally {
			saving = false;
		}
	}

	async function handleRevert() {
		if (!confirm("Revert this override? This will delete the override and fall back to the next cascade level.")) return;
		try {
			const api = createClientApiClient(async () => data.token);
			await api.delete(`/admin/prompts/${data.vertical}/${data.templateName}`);
			await invalidateAll();
		} catch (e) {
			console.error("Revert failed:", e);
		}
	}
</script>

<PageHeader title="{data.templateName}">
	{#snippet actions()}
		<div class="flex items-center gap-2">
			{#if prompt}
				<Badge variant={prompt.source_level === "filesystem" ? "outline" : "default"}>
					{sourceBadgeText(prompt.source_level)}
				</Badge>
			{/if}
			{#if syntaxValid === true}
				<span class="inline-flex items-center gap-1 text-xs text-green-600">
					<span class="h-2 w-2 rounded-full bg-green-500"></span> Syntax OK
				</span>
			{:else if syntaxValid === false}
				<span class="inline-flex items-center gap-1 text-xs text-red-600">
					<span class="h-2 w-2 rounded-full bg-red-500"></span> Syntax Error
				</span>
			{/if}
			{#if prompt?.source_level !== "filesystem"}
				<Button variant="outline" size="sm" onclick={handleRevert}>Revert</Button>
			{/if}
			<Button onclick={handleSave} disabled={saving || prompt?.source_level === "filesystem"}>
				{saving ? "Saving..." : "Save"}
			</Button>
		</div>
	{/snippet}
</PageHeader>

<div class="p-6">
	{#if syntaxErrors.length > 0}
		<div class="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
			{#each syntaxErrors as err}
				<p>{err}</p>
			{/each}
		</div>
	{/if}

	<Tabs items={tabs} bind:active={activeTab}>
		{#snippet content(tab)}
			{#if tab === "editor"}
				<div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
					<!-- Editor pane -->
					<div>
						<label class="mb-1 block text-sm font-medium text-[var(--netz-text-secondary)]">Template</label>
						<textarea
							bind:value={editContent}
							oninput={handleInput}
							class="h-[500px] w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3 font-mono text-sm focus:border-[var(--netz-primary)] focus:outline-none"
							spellcheck="false"
							disabled={prompt?.source_level === "filesystem"}
						></textarea>
					</div>
					<!-- Preview pane -->
					<div>
						<div class="mb-1 flex items-center justify-between">
							<label class="text-sm font-medium text-[var(--netz-text-secondary)]">Preview</label>
							<Button variant="ghost" size="sm" onclick={handlePreview} disabled={previewing}>
								{previewing ? "Rendering..." : "Refresh Preview"}
							</Button>
						</div>
						<div class="h-[500px] overflow-auto rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-3 text-sm whitespace-pre-wrap">
							{previewHtml || "Click 'Refresh Preview' or start typing to see rendered output."}
						</div>
					</div>
				</div>

			{:else if tab === "history"}
				{#if (data.versions as VersionInfo[]).length === 0}
					<p class="mt-4 text-sm text-[var(--netz-text-muted)]">No version history (filesystem template).</p>
				{:else}
					<div class="mt-4 divide-y divide-[var(--netz-border)] rounded-lg border border-[var(--netz-border)]">
						{#each data.versions as version}
							<div class="px-4 py-3">
								<div class="flex items-center justify-between">
									<span class="font-medium">Version {(version as VersionInfo).version}</span>
									<span class="text-xs text-[var(--netz-text-muted)]">
										{new Date((version as VersionInfo).created_at).toLocaleString()} by {(version as VersionInfo).updated_by}
									</span>
								</div>
								<details class="mt-1">
									<summary class="cursor-pointer text-xs text-[var(--netz-primary)]">View content</summary>
									<pre class="mt-2 max-h-48 overflow-auto rounded bg-[var(--netz-surface-alt)] p-2 text-xs">{(version as VersionInfo).content}</pre>
								</details>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		{/snippet}
	</Tabs>
</div>
