<!--
  Prompt Editor — split pane with textarea (left) and live preview (right).
  Validates on debounced keystrokes, shows syntax errors inline.
-->
<script lang="ts">
	import { SectionCard } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";

	let {
		vertical,
		templateName,
		token,
	}: {
		vertical: string;
		templateName: string;
		token: string;
	} = $props();

	let content = $state("");
	let preview = $state("");
	let previewErrors = $state<string[]>([]);
	let validationErrors = $state<string[]>([]);
	let sourceLevel = $state("filesystem");
	let version = $state<number | null>(null);
	let loading = $state(true);
	let saving = $state(false);
	let saveMessage = $state<string | null>(null);
	let previewDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	const api = createClientApiClient(() => Promise.resolve(token));

	async function loadPrompt() {
		loading = true;
		try {
			const result = await api.get<{
				content: string;
				source_level: string;
				version: number | null;
			}>(`/admin/prompts/${vertical}/${templateName}`);
			content = result.content;
			sourceLevel = result.source_level;
			version = result.version;
			await doPreview();
		} catch {
			content = "";
		} finally {
			loading = false;
		}
	}

	async function doPreview() {
		try {
			const result = await api.post<{ rendered: string; errors: string[] }>(
				`/admin/prompts/${vertical}/${templateName}/preview`,
				{ content, sample_data: {} },
			);
			preview = result.rendered;
			previewErrors = result.errors;
		} catch {
			previewErrors = ["Preview request failed"];
		}
	}

	async function doValidate() {
		try {
			const result = await api.post<{ valid: boolean; errors: string[] }>(
				`/admin/prompts/${vertical}/${templateName}/validate`,
				{ content },
			);
			validationErrors = result.errors;
		} catch {
			validationErrors = ["Validation request failed"];
		}
	}

	function onInput(value: string) {
		content = value;
		if (previewDebounceTimer) clearTimeout(previewDebounceTimer);
		previewDebounceTimer = setTimeout(() => {
			void doPreview();
			void doValidate();
		}, 500);
	}

	async function save() {
		saving = true;
		saveMessage = null;
		try {
			const result = await api.put<{ template_name: string; version: number }>(
				`/admin/prompts/${vertical}/${templateName}`,
				{ content },
			);
			version = result.version;
			sourceLevel = "global";
			saveMessage = `Saved (v${result.version})`;
			setTimeout(() => (saveMessage = null), 3000);
		} catch (e: unknown) {
			saveMessage = e instanceof Error ? e.message : "Save failed";
		} finally {
			saving = false;
		}
	}

	async function revert() {
		if (!confirm("Remove this override? The prompt will fall back to the next cascade level."))
			return;
		try {
			await api.delete(`/admin/prompts/${vertical}/${templateName}`);
			await loadPrompt();
		} catch {
			/* silent — loadPrompt will show current state */
		}
	}

	$effect(() => {
		// Track reactive props so the effect re-runs on change
		const _v = vertical;
		const _t = templateName;
		void loadPrompt();
	});

	const isReadonly = $derived(sourceLevel === "filesystem");
	const syntaxValid = $derived(validationErrors.length === 0);
</script>

<SectionCard title={templateName}>
	{#if loading}
		<p class="text-sm text-[var(--netz-text-muted)]">Loading template...</p>
	{:else}
		<!-- Header -->
		<div class="mb-3 flex items-center justify-between">
			<div class="flex items-center gap-2">
				<span
					class="h-2 w-2 rounded-full {syntaxValid ? 'bg-green-500' : 'bg-red-500'}"
				></span>
				<span class="text-xs text-[var(--netz-text-muted)]">
					{isReadonly
						? "Viewing filesystem template (read-only)"
						: `Editing ${sourceLevel} override`}
					{#if version}
						&middot; v{version}
					{/if}
				</span>
			</div>
			{#if saveMessage}
				<span class="text-xs text-[var(--netz-brand-primary)]">{saveMessage}</span>
			{/if}
		</div>

		<!-- Split Pane -->
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
			<!-- Left: Editor -->
			<div>
				<label class="mb-1 block text-xs text-[var(--netz-text-muted)]">
					Template (Jinja2)
				</label>
				<textarea
					value={content}
					oninput={(e) => onInput(e.currentTarget.value)}
					readonly={isReadonly}
					rows={20}
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3 font-mono text-xs text-[var(--netz-text-primary)] focus:border-[var(--netz-brand-primary)] focus:outline-none {isReadonly
						? 'opacity-60'
						: ''}"
					spellcheck="false"
				></textarea>
				{#if validationErrors.length > 0}
					<div class="mt-2 space-y-1">
						{#each validationErrors as err}
							<p class="text-xs text-red-500">{err}</p>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Right: Preview -->
			<div>
				<label class="mb-1 block text-xs text-[var(--netz-text-muted)]">Preview</label>
				<div
					class="h-full min-h-[20rem] overflow-auto rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-3"
				>
					{#if previewErrors.length > 0}
						<div class="space-y-1">
							{#each previewErrors as err}
								<p class="text-xs text-red-500">{err}</p>
							{/each}
						</div>
					{:else}
						<div class="prose prose-sm text-[var(--netz-text-primary)]">
							{@html preview}
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Actions -->
		{#if !isReadonly}
			<div class="mt-4 flex justify-between">
				<button
					onclick={revert}
					class="rounded-md border border-red-300 px-4 py-2 text-sm text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950"
				>
					Revert Override
				</button>
				<button
					onclick={save}
					disabled={saving || !syntaxValid}
					class="rounded-md bg-[var(--netz-brand-primary)] px-6 py-2 text-sm text-white hover:opacity-90 disabled:opacity-50"
				>
					{saving ? "Saving..." : "Save"}
				</button>
			</div>
		{/if}
	{/if}
</SectionCard>
