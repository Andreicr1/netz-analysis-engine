<!--
  LibraryShell — top-level orchestrator for the Wealth Library.

  Phase 3 of the Library frontend (spec §3.4 Fase 1 + §2.5). The
  shell owns the 3-pane desktop layout (tree | content | preview)
  and the in-memory state that the URL adapter and the future
  filter/search bar plug into. It is intentionally framework-only:
  zero data fetching happens here. The initial `LibraryTree` payload
  comes from the server loader; expansion / children fetching is
  delegated to a `TreeLoader` instance created in onMount and
  disposed in onDestroy so a route remount always starts clean.

  Layout decisions
  ----------------
  * Tree pane is fixed at 320px (spec §2.8 — desktop-first 1440px+).
  * Preview pane is fixed at 520px and renders a placeholder until
    Phase 5 lands the dynamic readers panel.
  * Content pane is fluid in between, capped at the standard
    `max-w-screen-2xl` cage by the wrapping route — no full-bleed.
  * Total height is `calc(100vh - 88px)` to respect the global
    layout cage pattern documented in CLAUDE.md /
    docs/reference/wealth-frontend-shell.md.
-->
<script lang="ts">
	import { getContext, onDestroy, onMount, untrack } from "svelte";
	import { goto } from "$app/navigation";
	import {
		createTreeLoader,
		type TreeLoader,
	} from "$lib/state/library/tree-loader.svelte";
	import {
		createUrlAdapter,
		type UrlAdapter,
	} from "$lib/state/library/url-adapter.svelte";
	import type { LibraryNode, LibraryTree } from "$lib/types/library";
	import LibraryBreadcrumbs from "./LibraryBreadcrumbs.svelte";
	import LibraryFilterBar from "./LibraryFilterBar.svelte";
	import LibrarySearchInput from "./LibrarySearchInput.svelte";
	import LibraryTreeView from "./LibraryTree.svelte";
	import LibraryViewToggle from "./LibraryViewToggle.svelte";

	interface Props {
		tree: LibraryTree;
		initialPath: string | null;
	}

	let { tree, initialPath }: Props = $props();

	const getToken =
		getContext<() => Promise<string>>("netz:getToken");

	// URL adapter must be created synchronously during script init so
	// the $effect inside it registers with the component lifecycle.
	const adapter: UrlAdapter = createUrlAdapter();

	let loader: TreeLoader | null = $state(null);
	let selectedPath = $state<string | null>(untrack(() => initialPath));
	let selectedNode = $state<LibraryNode | null>(null);

	onMount(() => {
		loader = createTreeLoader(getToken);
		// If the URL deep-linked into a folder path, expand every
		// ancestor so the row is visible. We snapshot via `untrack`
		// because the expansion is a one-shot action on mount; the
		// URL adapter (Phase 4) will pick up subsequent navigations.
		const path = untrack(() => initialPath);
		if (path && loader) {
			const segments = path.split("/").filter(Boolean);
			const partials: string[] = [];
			for (let i = 0; i < segments.length; i += 1) {
				partials.push(segments.slice(0, i + 1).join("/"));
			}
			for (const p of partials) {
				void loader.expand(p);
			}
		}
	});

	onDestroy(() => {
		loader?.dispose();
		loader = null;
		adapter.dispose();
	});

	function handleSelect(node: LibraryNode): void {
		selectedNode = node;
		selectedPath = node.path;
		// Mirror selection into the URL via SvelteKit's `goto`. The
		// catch-all route handles deep-linking back; query params are
		// preserved so future filters survive navigation.
		const target =
			node.node_type === "file" && node.id
				? `/library/${node.path}?id=${node.id}`
				: `/library/${node.path}`;
		void goto(target, { keepFocus: true, noScroll: true });
	}

	function handleNavigate(path: string | null): void {
		selectedPath = path;
		selectedNode = null;
		void goto(path ? `/library/${path}` : "/library", {
			keepFocus: true,
			noScroll: true,
		});
	}
</script>

<div class="library-shell">
	<header class="library-header">
		<div class="library-header__left">
			<LibrarySearchInput {adapter} />
		</div>
		<div class="library-header__right">
			<LibraryViewToggle {adapter} />
		</div>
	</header>

	<LibraryFilterBar {adapter} />
	<LibraryBreadcrumbs {selectedPath} onNavigate={handleNavigate} />

	<div class="library-grid">
		<aside class="pane pane--tree" aria-label="Library navigation">
			{#if adapter.state.view === "tree"}
				{#if loader}
					<LibraryTreeView
						{tree}
						{loader}
						{selectedPath}
						onSelect={handleSelect}
					/>
				{/if}
			{:else if adapter.state.view === "list"}
				<div class="view-placeholder">
					<p class="view-placeholder__title">List view</p>
					<p class="view-placeholder__sub">
						Flat list rendering ships in the next sprint. The
						URL contract is already wired so deep-links survive.
					</p>
				</div>
			{:else}
				<div class="view-placeholder">
					<p class="view-placeholder__title">Grid view</p>
					<p class="view-placeholder__sub">
						Card grid ships in the next sprint. The URL contract
						is already wired so deep-links survive.
					</p>
				</div>
			{/if}
		</aside>

		<section class="pane pane--content" aria-label="Library content">
			<div class="content-empty">
				<p class="content-empty__title">
					{#if selectedNode}
						{selectedNode.label}
					{:else if selectedPath}
						{selectedPath}
					{:else}
						Welcome to your Library
					{/if}
				</p>
				<p class="content-empty__sub">
					Pick a folder on the left to browse documents. The
					content list ships in the next sprint.
				</p>
			</div>
		</section>

		<aside class="pane pane--preview" aria-label="Library preview">
			<div class="preview-empty">
				<p class="preview-empty__title">Preview</p>
				<p class="preview-empty__sub">
					Select a document to read it inline. Reader integration
					is delivered in Phase 5.
				</p>
			</div>
		</aside>
	</div>
</div>

<style>
	.library-shell {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 88px);
		background: #141519;
		color: #cbccd1;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		border-radius: 12px;
		overflow: hidden;
	}

	.library-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 12px 20px;
		background: #141519;
		border-bottom: 1px solid #404249;
	}

	.library-header__left {
		flex: 1;
		display: flex;
		min-width: 0;
	}

	.library-header__right {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.view-placeholder {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 24px;
		color: #85a0bd;
	}

	.view-placeholder__title {
		font-size: 14px;
		font-weight: 700;
		color: #ffffff;
		margin: 0;
	}

	.view-placeholder__sub {
		font-size: 12px;
		margin: 0;
		line-height: 1.5;
	}

	.library-grid {
		flex: 1;
		display: grid;
		grid-template-columns: 320px minmax(0, 1fr) 520px;
		min-height: 0;
	}

	.pane {
		min-height: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.pane--tree {
		border-right: 1px solid #404249;
		background: #141519;
	}

	.pane--content {
		background: #141519;
		padding: 24px;
		overflow-y: auto;
	}

	.pane--preview {
		border-left: 1px solid #404249;
		background: #141519;
		padding: 24px;
		overflow-y: auto;
	}

	.content-empty,
	.preview-empty {
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: 480px;
		color: #85a0bd;
	}

	.content-empty__title,
	.preview-empty__title {
		font-size: 18px;
		font-weight: 700;
		color: #ffffff;
		margin: 0;
	}

	.content-empty__sub,
	.preview-empty__sub {
		font-size: 13px;
		color: #85a0bd;
		margin: 0;
		line-height: 1.5;
	}

	@media (max-width: 1280px) {
		.library-grid {
			grid-template-columns: 280px minmax(0, 1fr) 420px;
		}
	}

	@media (max-width: 1024px) {
		.library-grid {
			grid-template-columns: 240px minmax(0, 1fr);
		}
		.pane--preview {
			display: none;
		}
	}
</style>
