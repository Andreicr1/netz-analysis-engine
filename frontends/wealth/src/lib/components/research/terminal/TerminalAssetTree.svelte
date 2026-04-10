<!--
  TerminalAssetTree — hierarchical navigation for Research desk.
  Three levels: Portfolio Root → Asset Classes → Funds/Tickers.
  Click any node to update selectedNode.
-->
<script module lang="ts">
	export interface TreeNode {
		id: string;
		label: string;
		ticker?: string;
		type: "root" | "class" | "fund";
		children?: TreeNode[];
	}
</script>

<script lang="ts">
	interface Props {
		tree: TreeNode[];
		selectedId: string | null;
		onSelect: (node: TreeNode) => void;
	}

	let { tree, selectedId, onSelect }: Props = $props();

	let expanded = $state<Set<string>>(new Set(["root", "equities", "fixed-income", "alternatives"]));

	function toggle(nodeId: string) {
		const next = new Set(expanded);
		if (next.has(nodeId)) next.delete(nodeId);
		else next.add(nodeId);
		expanded = next;
	}

	function isExpanded(nodeId: string): boolean {
		return expanded.has(nodeId);
	}
</script>

<div class="at-root">
	<div class="at-header">
		<span class="at-title">ASSET TREE</span>
	</div>
	<div class="at-scroll">
		{#each tree as node}
			{@render treeNode(node, 0)}
		{/each}
	</div>
</div>

{#snippet treeNode(node: TreeNode, depth: number)}
	<div class="at-node" style="padding-left: {8 + depth * 14}px">
		{#if node.children && node.children.length > 0}
			<button
				class="at-toggle"
				onclick={() => toggle(node.id)}
				aria-expanded={isExpanded(node.id)}
			>
				{isExpanded(node.id) ? "[-]" : "[+]"}
			</button>
		{:else}
			<span class="at-leaf-spacer">&nbsp;&middot;&nbsp;</span>
		{/if}

		<button
			class="at-label"
			class:selected={selectedId === node.id}
			class:is-fund={node.type === "fund"}
			onclick={() => onSelect(node)}
		>
			{#if node.ticker}
				<span class="at-ticker">{node.ticker}</span>
			{/if}
			<span class="at-name">{node.label}</span>
		</button>
	</div>

	{#if node.children && isExpanded(node.id)}
		{#each node.children as child}
			{@render treeNode(child, depth + 1)}
		{/each}
	{/if}
{/snippet}

<style>
	.at-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: #0c1018;
		border-right: 1px solid rgba(255, 255, 255, 0.06);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #c8d0dc;
	}

	.at-header {
		display: flex;
		align-items: center;
		padding: 10px 12px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}

	.at-title {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: #5a6577;
		text-transform: uppercase;
	}

	.at-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		min-height: 0;
		padding: 4px 0;
	}

	.at-node {
		display: flex;
		align-items: center;
		gap: 2px;
		min-height: 24px;
	}

	.at-toggle {
		background: none;
		border: none;
		color: #5a6577;
		font-family: monospace;
		font-size: 10px;
		cursor: pointer;
		padding: 0 2px;
		flex-shrink: 0;
		width: 22px;
		text-align: center;
	}
	.at-toggle:hover {
		color: #8a94a6;
	}

	.at-leaf-spacer {
		width: 22px;
		text-align: center;
		color: #2a3040;
		font-size: 10px;
		flex-shrink: 0;
	}

	.at-label {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: #8a94a6;
		font-family: inherit;
		font-size: 11px;
		cursor: pointer;
		padding: 2px 6px;
		border-radius: 2px;
		text-align: left;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
		min-width: 0;
	}
	.at-label:hover {
		background: rgba(255, 255, 255, 0.03);
		color: #c8d0dc;
	}
	.at-label.selected {
		background: rgba(45, 126, 247, 0.10);
		color: #e2e8f0;
	}

	.at-ticker {
		font-weight: 700;
		color: #e2e8f0;
		font-size: 10px;
		letter-spacing: 0.04em;
		flex-shrink: 0;
	}
	.at-label.selected .at-ticker {
		color: #93bbfc;
	}

	.at-name {
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.at-label.is-fund {
		font-size: 10px;
	}
</style>
