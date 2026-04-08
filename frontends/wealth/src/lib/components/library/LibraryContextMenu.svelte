<!--
  LibraryContextMenu — right-click menu for Library tree rows.

  Phase 6 of the Library frontend (spec §3.4 Fase 6). The menu is
  intentionally simple: it's a positioned popover anchored to the
  cursor, dismissed on click outside or Escape. Items are
  context-aware — folders only show "Open"; files show Open +
  Preview + Pin/Unpin + Star/Unstar.
-->
<script lang="ts">
	import { onDestroy } from "svelte";
	import Eye from "lucide-svelte/icons/eye";
	import FolderOpen from "lucide-svelte/icons/folder-open";
	import Pin from "lucide-svelte/icons/pin";
	import PinOff from "lucide-svelte/icons/pin-off";
	import Star from "lucide-svelte/icons/star";
	import StarOff from "lucide-svelte/icons/star-off";
	import type { LibraryNode } from "$lib/types/library";

	interface Props {
		node: LibraryNode | null;
		x: number;
		y: number;
		open: boolean;
		isPinned: boolean;
		isStarred: boolean;
		onClose: () => void;
		onOpen: (node: LibraryNode) => void;
		onPreview: (node: LibraryNode) => void;
		onTogglePin: (node: LibraryNode) => void;
		onToggleStar: (node: LibraryNode) => void;
	}

	let {
		node,
		x,
		y,
		open,
		isPinned,
		isStarred,
		onClose,
		onOpen,
		onPreview,
		onTogglePin,
		onToggleStar,
	}: Props = $props();

	const isFile = $derived(node?.node_type === "file");

	function handleGlobalClick(event: MouseEvent): void {
		if (!open) return;
		const target = event.target as Node | null;
		const menu = document.getElementById("library-context-menu");
		if (menu && target && !menu.contains(target)) {
			onClose();
		}
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (!open) return;
		if (event.key === "Escape") {
			event.preventDefault();
			onClose();
		} else if (event.key.toLowerCase() === "s" && node) {
			event.preventDefault();
			onToggleStar(node);
			onClose();
		} else if (event.key.toLowerCase() === "p" && node) {
			event.preventDefault();
			onTogglePin(node);
			onClose();
		}
	}

	$effect(() => {
		if (open) {
			document.addEventListener("click", handleGlobalClick);
			document.addEventListener("keydown", handleKeydown);
		}
		return () => {
			document.removeEventListener("click", handleGlobalClick);
			document.removeEventListener("keydown", handleKeydown);
		};
	});

	onDestroy(() => {
		document.removeEventListener("click", handleGlobalClick);
		document.removeEventListener("keydown", handleKeydown);
	});
</script>

{#if open && node}
	<div
		id="library-context-menu"
		class="menu"
		style:left="{x}px"
		style:top="{y}px"
		role="menu"
		aria-label="Library actions"
	>
		<button
			type="button"
			class="menu__item"
			role="menuitem"
			onclick={() => {
				onOpen(node);
				onClose();
			}}
		>
			<FolderOpen size={14} />
			<span>Open</span>
		</button>

		{#if isFile}
			<button
				type="button"
				class="menu__item"
				role="menuitem"
				onclick={() => {
					onPreview(node);
					onClose();
				}}
			>
				<Eye size={14} />
				<span>Preview</span>
			</button>

			<div class="menu__sep" role="separator"></div>

			<button
				type="button"
				class="menu__item"
				role="menuitem"
				onclick={() => {
					onTogglePin(node);
					onClose();
				}}
			>
				{#if isPinned}
					<PinOff size={14} />
					<span>Unpin</span>
				{:else}
					<Pin size={14} />
					<span>Pin</span>
				{/if}
				<kbd class="menu__kbd">P</kbd>
			</button>

			<button
				type="button"
				class="menu__item"
				role="menuitem"
				onclick={() => {
					onToggleStar(node);
					onClose();
				}}
			>
				{#if isStarred}
					<StarOff size={14} />
					<span>Unstar</span>
				{:else}
					<Star size={14} />
					<span>Star</span>
				{/if}
				<kbd class="menu__kbd">S</kbd>
			</button>
		{/if}
	</div>
{/if}

<style>
	.menu {
		position: fixed;
		z-index: 9999;
		min-width: 200px;
		background: #1d1f25;
		border: 1px solid #404249;
		border-radius: 8px;
		padding: 4px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		color: #cbccd1;
	}

	.menu__item {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 7px 12px;
		border: none;
		background: transparent;
		color: #cbccd1;
		font-family: inherit;
		font-size: 13px;
		text-align: left;
		cursor: pointer;
		border-radius: 6px;
	}

	.menu__item:hover {
		background: color-mix(in srgb, #0177fb 22%, #141519);
		color: #ffffff;
	}

	.menu__sep {
		height: 1px;
		background: #404249;
		margin: 4px 0;
	}

	.menu__kbd {
		margin-left: auto;
		font-family: var(--ii-font-mono, ui-monospace, monospace);
		font-size: 10px;
		color: #85a0bd;
		padding: 1px 5px;
		border: 1px solid #404249;
		border-radius: 4px;
	}
</style>
