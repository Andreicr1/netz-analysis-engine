<!--
  LibraryTree — virtualised hierarchical tree for the Wealth Library.

  Phase 3 of the Library frontend (spec §3.4 Fase 1). The component
  flattens the lazy-loaded folder hierarchy into an array of visible
  rows (depth annotated) and hands it to `@tanstack/svelte-virtual`'s
  `createVirtualizer` so only the rows inside the scroll viewport
  render. The institutional target is "5000 nodes at 60fps" which
  the virtualiser meets trivially with a fixed `estimateSize`.

  All expansion + child fetching is delegated to a `TreeLoader`
  instance owned by the parent shell — see
  `lib/state/library/tree-loader.svelte.ts`. The component itself
  carries no fetching logic, only flattening and selection.
-->
<script lang="ts">
	import { createVirtualizer } from "@tanstack/svelte-virtual";
	import type { LibraryNode, LibraryTree } from "$wealth/types/library";
	import type { TreeLoader } from "$wealth/state/library/tree-loader.svelte";
	import LibraryTreeNode from "./LibraryTreeNode.svelte";

	interface Props {
		tree: LibraryTree;
		loader: TreeLoader;
		selectedPath: string | null;
		onSelect: (node: LibraryNode) => void;
		onContext?: (event: MouseEvent, node: LibraryNode) => void;
	}

	let {
		tree,
		loader,
		selectedPath,
		onSelect,
		onContext,
	}: Props = $props();

	interface FlatRow {
		key: string;
		node: LibraryNode;
		depth: number;
	}

	// ── Flatten the tree into a visible-row list ────────────────────
	//
	// The server hands us L1 + L2 in `tree.roots` already linearised
	// (each root carries the full encoded path). When the user expands
	// any folder, the loader caches its `LibraryNodePage.items` under
	// the same encoded path, and we splice them in below the parent.
	//
	// We deliberately compute this in $derived rather than $effect so
	// the virtualiser sees a brand-new identity every time the
	// underlying data changes — no manual invalidation needed.
	const flatRows = $derived.by<FlatRow[]>(() => {
		const rows: FlatRow[] = [];

		// Group L1 roots vs their L2 children. The server returns
		// every L1 + L2 entry as a separate `roots` element; the L2
		// rows live under their parent L1's path string.
		const byParent = new Map<string, LibraryNode[]>();
		const l1Nodes: LibraryNode[] = [];
		for (const node of tree.roots) {
			const segments = node.path.split("/");
			if (segments.length === 1) {
				l1Nodes.push(node);
			} else {
				const parent = segments.slice(0, -1).join("/");
				const bucket = byParent.get(parent);
				if (bucket) {
					bucket.push(node);
				} else {
					byParent.set(parent, [node]);
				}
			}
		}

		function pushNode(node: LibraryNode, depth: number): void {
			rows.push({ key: `${node.path}|${node.id ?? "f"}`, node, depth });

			// Folders contribute their seeded L2 children (from the
			// initial /library/tree response) plus any lazily fetched
			// deeper children once the loader has cached them.
			if (node.node_type !== "folder" || !loader.expanded.has(node.path)) {
				return;
			}

			const seeded = byParent.get(node.path) ?? [];
			for (const child of seeded) {
				pushNode(child, depth + 1);
			}

			const fetched = loader.folders[node.path];
			if (fetched) {
				if (fetched.loading && fetched.children.length === 0) {
					rows.push({
						key: `${node.path}|loading`,
						node: {
							node_type: "folder",
							path: `${node.path}/__loading`,
							label: "Loading...",
							child_count: null,
						},
						depth: depth + 1,
					});
				} else if (fetched.error && fetched.children.length === 0) {
					rows.push({
						key: `${node.path}|error`,
						node: {
							node_type: "folder",
							path: `${node.path}/__error`,
							label: fetched.error,
							child_count: null,
						},
						depth: depth + 1,
					});
				}
				for (const child of fetched.children) {
					pushNode(child, depth + 1);
				}
			}
		}

		for (const root of l1Nodes) {
			pushNode(root, 0);
		}

		return rows;
	});

	// ── Virtualisation ──────────────────────────────────────────────
	let scrollEl = $state<HTMLDivElement | undefined>(undefined);
	const ROW_HEIGHT = 32;

	// `createVirtualizer` from @tanstack/svelte-virtual returns a
	// Svelte readable store. We pass getters so the option object
	// stays stable while the underlying values stay reactive — the
	// store re-renders the visible window whenever `count` or the
	// scroll element flip.
	const virtualizer = createVirtualizer<HTMLDivElement, HTMLDivElement>({
		get count() {
			return flatRows.length;
		},
		getScrollElement: () => scrollEl ?? null,
		estimateSize: () => ROW_HEIGHT,
		overscan: 12,
	});

	// ── Keyboard navigation between rows ────────────────────────────
	let focusedIndex = $state(0);

	function handleListKeydown(event: KeyboardEvent): void {
		if (flatRows.length === 0) return;
		if (event.key === "ArrowDown") {
			event.preventDefault();
			focusedIndex = Math.min(flatRows.length - 1, focusedIndex + 1);
			$virtualizer.scrollToIndex(focusedIndex, { align: "auto" });
		} else if (event.key === "ArrowUp") {
			event.preventDefault();
			focusedIndex = Math.max(0, focusedIndex - 1);
			$virtualizer.scrollToIndex(focusedIndex, { align: "auto" });
		} else if (event.key === "Home") {
			event.preventDefault();
			focusedIndex = 0;
			$virtualizer.scrollToIndex(0, { align: "start" });
		} else if (event.key === "End") {
			event.preventDefault();
			focusedIndex = flatRows.length - 1;
			$virtualizer.scrollToIndex(focusedIndex, { align: "end" });
		}
	}

	function isLoading(node: LibraryNode): boolean {
		if (node.node_type !== "folder") return false;
		return loader.folders[node.path]?.loading ?? false;
	}

	function isSelected(node: LibraryNode): boolean {
		if (selectedPath === null) return false;
		if (node.node_type === "file" && node.id) {
			return selectedPath === node.id;
		}
		return selectedPath === node.path;
	}
</script>

<div
	bind:this={scrollEl}
	class="tree-scroll"
	role="tree"
	aria-label="Wealth Library navigation"
	tabindex="0"
	onkeydown={handleListKeydown}
>
	<div class="tree-spacer" style:height="{$virtualizer.getTotalSize()}px">
		{#each $virtualizer.getVirtualItems() as item (flatRows[item.index]?.key ?? item.key)}
			{@const row = flatRows[item.index]}
			{#if row}
				<div
					class="tree-row-wrap"
					style:transform="translateY({item.start}px)"
					style:height="{ROW_HEIGHT}px"
					oncontextmenu={(e) => onContext?.(e, row.node)}
					role="presentation"
				>
					<LibraryTreeNode
						node={row.node}
						depth={row.depth}
						expanded={loader.expanded.has(row.node.path)}
						selected={isSelected(row.node)}
						loading={isLoading(row.node)}
						onToggle={(p) => {
							focusedIndex = item.index;
							void loader.toggle(p);
						}}
						onSelect={(n) => {
							focusedIndex = item.index;
							onSelect(n);
						}}
					/>
				</div>
			{/if}
		{/each}
	</div>
</div>

<style>
	.tree-scroll {
		height: 100%;
		overflow-y: auto;
		overflow-x: hidden;
		background: #141519;
		padding: 8px 6px;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		scrollbar-width: thin;
		scrollbar-color: #404249 transparent;
	}

	.tree-scroll:focus-visible {
		outline: 2px solid #0177fb;
		outline-offset: -2px;
		border-radius: 8px;
	}

	.tree-scroll::-webkit-scrollbar {
		width: 8px;
	}

	.tree-scroll::-webkit-scrollbar-thumb {
		background: #404249;
		border-radius: 4px;
	}

	.tree-spacer {
		width: 100%;
		position: relative;
	}

	.tree-row-wrap {
		position: absolute;
		inset: 0 0 auto 0;
	}
</style>
