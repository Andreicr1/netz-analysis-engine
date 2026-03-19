<!--
  DD Report detail — chapter navigation sidebar + content display.
  Download PDF, regenerate with confirmation.
-->
<script lang="ts">
	import { Card, Button, EmptyState } from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import DOMPurify from "dompurify";

	/** Render Markdown as safe HTML — converts basic Markdown then sanitizes with DOMPurify. */
	function renderSafeMarkdown(md: string): string {
		// Convert basic Markdown to HTML (headers, bold, italic, lists, code blocks)
		let html = md
			.replace(/^### (.+)$/gm, "<h3>$1</h3>")
			.replace(/^## (.+)$/gm, "<h2>$1</h2>")
			.replace(/^# (.+)$/gm, "<h1>$1</h1>")
			.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
			.replace(/\*(.+?)\*/g, "<em>$1</em>")
			.replace(/`(.+?)`/g, "<code>$1</code>")
			.replace(/^- (.+)$/gm, "<li>$1</li>")
			.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)
			.replace(/\n\n/g, "</p><p>")
			.replace(/\n/g, "<br/>");
		html = `<p>${html}</p>`;
		// Sanitize with DOMPurify — handles mXSS, namespace escapes, all known bypass vectors
		if (typeof window !== "undefined") {
			html = DOMPurify.sanitize(html);
		}
		return html;
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type Chapter = {
		chapter_number: number;
		title: string;
		content: string;
		status: string;
	};

	let report = $derived(data.report as Record<string, unknown>);
	let chapters = $derived((report?.chapters ?? []) as Chapter[]);
	let activeChapter = $state(0);
	let downloading = $state(false);
	let showRegenConfirm = $state(false);
	let regenerating = $state(false);
	let actionError = $state<string | null>(null);

	async function downloadPDF() {
		downloading = true;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/dd-reports/${data.reportId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `dd-report-${data.reportId}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloading = false;
		}
	}

	async function regenerate() {
		regenerating = true;
		showRegenConfirm = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${data.reportId}/regenerate`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Regeneration failed";
		} finally {
			regenerating = false;
		}
	}
</script>

<div class="flex h-full">
	<!-- Chapter sidebar -->
	<aside class="w-64 shrink-0 border-r border-(--netz-border) bg-(--netz-surface-panel) p-4">
		<h3 class="mb-3 text-sm font-semibold text-(--netz-text-secondary)">Chapters</h3>
		{#if chapters.length === 0}
			<p class="text-xs text-(--netz-text-muted)">No chapters yet.</p>
		{:else}
			<nav class="space-y-1">
				{#each chapters as chapter, i (chapter.chapter_number)}
					<button
						class="w-full rounded-md px-3 py-2 text-left text-xs transition-colors
							{activeChapter === i ? 'bg-(--netz-brand-primary)/10 font-medium text-(--netz-brand-primary)' : 'text-(--netz-text-secondary) hover:bg-(--netz-surface-highlight)'}"
						onclick={() => activeChapter = i}
					>
						{chapter.chapter_number}. {chapter.title}
					</button>
				{/each}
			</nav>
		{/if}

		<div class="mt-6 space-y-2">
			<ActionButton
				onclick={downloadPDF}
				loading={downloading}
				loadingText="Downloading..."
				class="w-full"
				size="sm"
			>
				Download PDF
			</ActionButton>
			<ActionButton
				variant="outline"
				onclick={() => showRegenConfirm = true}
				loading={regenerating}
				loadingText="..."
				class="w-full"
				size="sm"
			>
				Regenerate
			</ActionButton>
		</div>
	</aside>

	<!-- Chapter content -->
	<main class="flex-1 overflow-y-auto p-6">
		{#if actionError}
			<div class="mb-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{actionError}
			</div>
		{/if}

		{#if chapters.length === 0}
			<EmptyState title="No Chapters" description="Report chapters will appear here after generation." />
		{:else if chapters[activeChapter]}
			<div>
				<h2 class="mb-4 text-xl font-semibold text-(--netz-text-primary)">
					{chapters[activeChapter].chapter_number}. {chapters[activeChapter].title}
				</h2>
				<Card class="prose prose-sm max-w-none p-6 text-(--netz-text-primary)">
					<!-- Sanitized Markdown rendering — strips scripts/handlers/javascript: -->
					<div>{@html renderSafeMarkdown(chapters[activeChapter].content)}</div>
				</Card>
			</div>
		{/if}
	</main>
</div>

<ConfirmDialog
	bind:open={showRegenConfirm}
	title="Regenerate Report"
	message="This will regenerate all chapters. Continue?"
	confirmLabel="Regenerate"
	confirmVariant="default"
	onConfirm={regenerate}
	onCancel={() => showRegenConfirm = false}
/>
