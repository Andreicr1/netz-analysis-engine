<!--
  LibraryTreeNode — single virtualised row inside the LibraryTree.

  Phase 3 of the Wealth Library frontend (spec §3.4 Fase 1). The
  node is intentionally dumb: it receives a flattened representation
  with the depth pre-computed by `LibraryTree`, plus a handful of
  callbacks. All expand/collapse + selection state lives upstream
  in the `tree-loader.svelte.ts` store and the URL adapter, so this
  component never owns reactive truth on its own — it just renders.

  Both folders and files use the same row height so the virtualiser
  can keep `estimateSize` constant and free of layout thrash.
-->
<script lang="ts">
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import FileText from "lucide-svelte/icons/file-text";
	import Folder from "lucide-svelte/icons/folder";
	import FolderOpen from "lucide-svelte/icons/folder-open";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import type { LibraryNode } from "$lib/types/library";

	interface Props {
		node: LibraryNode;
		depth: number;
		expanded: boolean;
		selected: boolean;
		loading: boolean;
		onToggle: (path: string) => void;
		onSelect: (node: LibraryNode) => void;
	}

	let {
		node,
		depth,
		expanded,
		selected,
		loading,
		onToggle,
		onSelect,
	}: Props = $props();

	const isFolder = $derived(node.node_type === "folder");

	function handleClick(): void {
		if (isFolder) {
			onToggle(node.path);
		} else {
			onSelect(node);
		}
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === "Enter" || event.key === " ") {
			event.preventDefault();
			handleClick();
		} else if (event.key === "ArrowRight" && isFolder && !expanded) {
			event.preventDefault();
			onToggle(node.path);
		} else if (event.key === "ArrowLeft" && isFolder && expanded) {
			event.preventDefault();
			onToggle(node.path);
		}
	}

	const indent = $derived(depth * 14);
	const hoverTitle = $derived(
		isFolder && node.child_count != null
			? `${node.label} — ${node.child_count} item${node.child_count === 1 ? "" : "s"}`
			: (node.label ?? ""),
	);
</script>

<button
	type="button"
	class="row"
	class:row--selected={selected}
	class:row--folder={isFolder}
	style:padding-left="{8 + indent}px"
	role="treeitem"
	aria-level={depth + 1}
	aria-expanded={isFolder ? expanded : undefined}
	aria-selected={selected}
	title={hoverTitle}
	onclick={handleClick}
	onkeydown={handleKeydown}
>
	{#if isFolder}
		<span class="chevron" class:chevron--open={expanded}>
			<ChevronRight size={12} />
		</span>
	{:else}
		<span class="chevron chevron--placeholder"></span>
	{/if}

	<span class="icon">
		{#if loading}
			<Loader2 size={14} class="spin" />
		{:else if isFolder && expanded}
			<FolderOpen size={14} />
		{:else if isFolder}
			<Folder size={14} />
		{:else}
			<FileText size={14} />
		{/if}
	</span>

	<span class="label">{node.label}</span>

	{#if isFolder && node.child_count != null && node.child_count > 0}
		<span class="count">{node.child_count}</span>
	{/if}
</button>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		height: 32px;
		border: none;
		background: transparent;
		color: #cbccd1;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		font-size: 13px;
		font-weight: 500;
		text-align: left;
		cursor: pointer;
		padding: 0 12px 0 8px;
		border-radius: 6px;
		transition: background-color 120ms ease, color 120ms ease;
		white-space: nowrap;
		overflow: hidden;
	}

	.row:hover {
		background: #1d1f25;
		color: #ffffff;
	}

	.row:focus-visible {
		outline: 2px solid #0177fb;
		outline-offset: -2px;
	}

	.row--selected {
		background: color-mix(in srgb, #0177fb 18%, #141519);
		color: #ffffff;
	}

	.row--selected .count { color: #ffffff; }

	.chevron {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 14px;
		height: 14px;
		color: #85a0bd;
		transition: transform 120ms ease;
	}

	.chevron--open { transform: rotate(90deg); }
	.chevron--placeholder { width: 14px; height: 14px; }

	.icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		color: #85a0bd;
		flex-shrink: 0;
	}

	.row--selected .icon,
	.row:hover .icon { color: #ffffff; }

	.label {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.count {
		font-size: 11px;
		font-weight: 600;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
		padding: 1px 6px;
		border-radius: 999px;
		background: #1d1f25;
		flex-shrink: 0;
	}

	:global(.spin) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
