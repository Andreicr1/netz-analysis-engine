<!--
	TerminalContextRail.svelte — entity-scoped right rail.
	======================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell, Appendix B navigation flow.

	Right-side 280px rail that appears when the URL contains
	`?entity=<kind>:<id>` and disappears entirely otherwise. Supports
	fund / portfolio / manager / sector / regime entity kinds
	(matching FocusMode.entityKind).

	Snippet-based content composition: the caller passes a `content`
	snippet typed with `Snippet<[{ kind, id }]>` so the rail renders
	entity-specific metadata without the primitive knowing domain
	details. A default card shows kind + id when no snippet is
	provided.

	Collapse to 32px sliver with a vertical CTX label preserving the
	grid column width. TerminalShell owns the `[` / `]` keyboard
	shortcuts and passes the `collapsed` state down as a prop — the
	rail stays purely presentational.

	Z-index var(--terminal-z-rail) = 20.
-->
<script lang="ts">
	import type { Snippet } from "svelte";
	import { fly } from "svelte/transition";
	import { svelteTransitionFor } from "@investintell/ui";

	export type TerminalContextRailEntityKind =
		| "fund"
		| "portfolio"
		| "manager"
		| "sector"
		| "regime";

	export interface TerminalContextRailEntity {
		kind: TerminalContextRailEntityKind;
		id: string;
	}

	interface TerminalContextRailProps {
		/**
		 * Currently-pinned entity. Null when no entity is in the URL;
		 * in that case the component returns nothing.
		 */
		entity: TerminalContextRailEntity | null;
		/**
		 * Optional content snippet. If provided, the rail renders it
		 * with the entity as parameter. If absent, a minimal default
		 * card listing kind + id is rendered.
		 */
		content?: Snippet<[TerminalContextRailEntity]>;
		/**
		 * Collapsed state controlled externally. TerminalShell
		 * handles the `[` / `]` keyboard shortcuts and flips this.
		 */
		collapsed: boolean;
	}

	let { entity, content, collapsed }: TerminalContextRailProps = $props();

	function kindLabel(kind: TerminalContextRailEntityKind): string {
		switch (kind) {
			case "fund":
				return "FUND";
			case "portfolio":
				return "PORTFOLIO";
			case "manager":
				return "MANAGER";
			case "sector":
				return "SECTOR";
			case "regime":
				return "REGIME";
		}
	}
</script>

{#if entity !== null}
	{#if collapsed}
		<aside class="tcr-rail tcr-rail--collapsed" aria-label="Context rail (collapsed)">
			<span class="tcr-collapsed-label">CTX</span>
		</aside>
	{:else}
		<aside
			class="tcr-rail tcr-rail--expanded"
			aria-label="Context rail"
			in:fly={{ x: 16, ...svelteTransitionFor("secondary") }}
		>
			<header class="tcr-header">
				<span class="tcr-brand">[ CTX · {kindLabel(entity.kind)} ]</span>
				<span class="tcr-entity-id" title={entity.id}>{entity.id}</span>
			</header>
			<div class="tcr-body">
				{#if content}
					{@render content(entity)}
				{:else}
					<div class="tcr-default-card">
						<div class="tcr-default-row">
							<span class="tcr-default-label">KIND</span>
							<span class="tcr-default-value">{kindLabel(entity.kind)}</span>
						</div>
						<div class="tcr-default-row">
							<span class="tcr-default-label">ID</span>
							<span class="tcr-default-value">{entity.id}</span>
						</div>
						<p class="tcr-default-hint">
							Bind a <code>content</code> snippet to fill this rail with
							entity-specific metadata.
						</p>
					</div>
				{/if}
			</div>
		</aside>
	{/if}
{/if}

<style>
	.tcr-rail {
		position: relative;
		z-index: var(--terminal-z-rail);
		background: var(--terminal-bg-panel);
		border-left: var(--terminal-border-hairline);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		box-sizing: border-box;
		height: 100%;
		overflow: hidden;
	}

	.tcr-rail--expanded {
		width: 280px;
		display: flex;
		flex-direction: column;
	}

	.tcr-rail--collapsed {
		width: 32px;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: var(--terminal-space-4);
	}

	.tcr-collapsed-label {
		writing-mode: vertical-rl;
		transform: rotate(180deg);
		font-size: var(--terminal-text-10);
		letter-spacing: 0.18em;
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.tcr-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-2);
		height: 32px;
		padding: 0 var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
		flex-shrink: 0;
	}

	.tcr-brand {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-accent-amber);
	}

	.tcr-entity-id {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
		max-width: 140px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tcr-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: var(--terminal-space-3);
	}

	.tcr-default-card {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-3);
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-void);
	}

	.tcr-default-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.tcr-default-label {
		color: var(--terminal-fg-tertiary);
	}

	.tcr-default-value {
		color: var(--terminal-fg-primary);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		max-width: 180px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tcr-default-hint {
		margin: 0;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		line-height: var(--terminal-leading-normal);
	}

	.tcr-default-hint code {
		color: var(--terminal-fg-tertiary);
		background: var(--terminal-bg-panel-raised);
		padding: 0 3px;
	}
</style>
