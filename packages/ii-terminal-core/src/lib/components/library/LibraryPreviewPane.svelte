<!--
  LibraryPreviewPane — dynamic reader host for the Wealth Library.

  Phase 5 of the Library frontend (spec §3.4 Fase 5). Picks the
  right standalone reader (`DDReportBody`, `ContentBody`,
  `MacroReviewBody`) based on the `source_table` discriminator
  returned by `GET /library/documents/{id}` and renders it under a
  small toolbar with the title, kind badge and a fullscreen toggle.

  Dynamic import discipline
  -------------------------
  None of the three reader bodies are imported statically — that
  would defeat the whole point of the per-source code split. Instead
  we resolve the right module via a `dynamic import()` factory inside
  a Svelte `{#await}` block. The factories are memoised by source
  table so a re-render of the same kind does not re-fetch the
  chunk.

  Race condition discipline
  -------------------------
  All fetching lives upstream in `preview-loader.svelte.ts` which
  carries the AbortController + MountedGuard pair. The pane only
  reads `loader.state` so it cannot trigger a stale render itself —
  even if the dynamic import resolves out of order, the underlying
  `document` reference is the latest because it's a single source
  of truth in the loader's $state.
-->
<script lang="ts">
	import type { Component } from "svelte";
	import Maximize2 from "lucide-svelte/icons/maximize-2";
	import Minimize2 from "lucide-svelte/icons/minimize-2";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import type { PreviewLoader } from "../../state/library/preview-loader.svelte";
	import type { UrlAdapter } from "../../state/library/url-adapter.svelte";
	import type { LibraryDocumentDetail } from "../../types/library";

	interface Props {
		loader: PreviewLoader;
		adapter: UrlAdapter;
	}

	let { loader, adapter }: Props = $props();

	// Dynamic-import factories per source table. Each loader returns
	// a Promise<{ default: Component }> that Svelte's {#await} can
	// consume directly. Vite ships them as separate chunks so the
	// initial Library route never pays the cost of all three readers.
	const READER_LOADERS: Record<
		string,
		() => Promise<{ default: Component<Record<string, unknown>> }>
	> = {
		dd_reports: () =>
			import("./readers/DDReportBody.svelte") as Promise<{
				default: Component<Record<string, unknown>>;
			}>,
		wealth_content: () =>
			import("./readers/ContentBody.svelte") as Promise<{
				default: Component<Record<string, unknown>>;
			}>,
		macro_reviews: () =>
			import("./readers/MacroReviewBody.svelte") as Promise<{
				default: Component<Record<string, unknown>>;
			}>,
	};

	function readerProps(doc: LibraryDocumentDetail): Record<string, unknown> {
		// The three readers expose different prop names for the id.
		// We translate the discriminator into the right shape so the
		// preview pane stays the only place that knows the mapping.
		switch (doc.source_table) {
			case "dd_reports":
				return { reportId: doc.source_id };
			case "wealth_content":
				return { id: doc.source_id };
			case "macro_reviews":
				return { reviewId: doc.source_id };
			default:
				return {};
		}
	}

	const isFullscreen = $derived(adapter.state.preview === "fullscreen");

	function toggleFullscreen(): void {
		adapter.setPreview(isFullscreen ? "inline" : "fullscreen");
	}

	function clearSelection(): void {
		adapter.setSelectedId(null);
		loader.clear();
	}
</script>

<section class="preview" aria-label="Library document preview">
	{#if loader.state.loading && !loader.state.document}
		<div class="preview__loading">
			<div class="preview__spinner" aria-hidden="true"></div>
			<p>Loading document…</p>
		</div>
	{:else if loader.state.error}
		<PanelErrorState
			title="Unable to load document"
			message={loader.state.error}
			onRetry={() =>
				adapter.state.selectedId
					? loader.loadDocument(adapter.state.selectedId)
					: undefined}
		/>
	{:else if !loader.state.document}
		<PanelEmptyState
			title="Select a document"
			message="Pick a document on the left to read it inline. The preview opens in place — no full-page navigation needed."
		/>
	{:else}
		{@const doc = loader.state.document}
		<header class="preview__bar">
			<div class="preview__title">
				<span class="preview__kind">{doc.kind}</span>
				<span class="preview__name">{doc.title}</span>
			</div>
			<div class="preview__actions">
				<button
					type="button"
					class="preview__btn"
					title={isFullscreen ? "Exit fullscreen" : "View fullscreen"}
					aria-pressed={isFullscreen}
					onclick={toggleFullscreen}
				>
					{#if isFullscreen}
						<Minimize2 size={14} />
					{:else}
						<Maximize2 size={14} />
					{/if}
				</button>
				<button
					type="button"
					class="preview__btn"
					title="Close preview"
					onclick={clearSelection}
				>
					Close
				</button>
			</div>
		</header>

		<div class="preview__body">
			{#if READER_LOADERS[doc.source_table]}
				{#await READER_LOADERS[doc.source_table]!()}
					<div class="preview__loading">
						<div class="preview__spinner" aria-hidden="true"></div>
						<p>Loading reader…</p>
					</div>
				{:then mod}
					{@const Reader = mod.default}
					<Reader {...readerProps(doc)} />
				{:catch err}
					<PanelErrorState
						title="Reader failed to load"
						message={err instanceof Error ? err.message : String(err)}
					/>
				{/await}
			{:else}
				<PanelEmptyState
					title="Unsupported document"
					message="This Library entry has no preview renderer yet."
				/>
			{/if}
		</div>
	{/if}
</section>

<style>
	.preview {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
		color: #cbccd1;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
	}

	.preview__bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 10px 16px;
		border-bottom: 1px solid #404249;
		background: #141519;
	}

	.preview__title {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		flex: 1;
	}

	.preview__kind {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #85a0bd;
	}

	.preview__name {
		font-size: 14px;
		font-weight: 700;
		color: #ffffff;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.preview__actions {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.preview__btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 5px 10px;
		border: 1px solid #404249;
		background: #1d1f25;
		color: #cbccd1;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		border-radius: 6px;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease;
	}

	.preview__btn:hover {
		color: #ffffff;
		border-color: #0177fb;
	}

	.preview__btn[aria-pressed="true"] {
		background: color-mix(in srgb, #0177fb 22%, #141519);
		color: #ffffff;
		border-color: #0177fb;
	}

	.preview__body {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}

	.preview__loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 48px 24px;
		color: #85a0bd;
		font-size: 13px;
	}

	.preview__spinner {
		width: 24px;
		height: 24px;
		border: 2px solid #404249;
		border-top-color: #0177fb;
		border-radius: 50%;
		animation: preview-spin 0.8s linear infinite;
	}

	@keyframes preview-spin {
		to { transform: rotate(360deg); }
	}
</style>
