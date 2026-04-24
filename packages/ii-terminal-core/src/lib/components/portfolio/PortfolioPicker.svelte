<!--
  PortfolioPicker — replaces the raw <select> in PortfolioTabContent.

  Populated state: list with preview (display_name, state badge,
  holdings count, last build timestamp). Empty state: "Create your
  first model portfolio" with single-click flow.

  Keyboard: arrow keys navigate, enter selects.
-->
<script lang="ts">
	import { formatDateTime, formatNumber } from "@investintell/ui";
	import type { ModelPortfolio } from "../../types/model-portfolio";

	interface Props {
		portfolios: ModelPortfolio[];
		selectedId: string | null;
		onSelect: (id: string) => void;
		onCreate: () => void;
	}

	let { portfolios, selectedId, onSelect, onCreate }: Props = $props();

	let isOpen = $state(false);
	let focusIndex = $state(-1);

	const selected = $derived(
		portfolios.find((p) => p.id === selectedId) ?? null,
	);

	function toggle() {
		isOpen = !isOpen;
		if (isOpen) {
			focusIndex = portfolios.findIndex((p) => p.id === selectedId);
		}
	}

	function select(p: ModelPortfolio) {
		onSelect(p.id);
		isOpen = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!isOpen) {
			if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
				e.preventDefault();
				isOpen = true;
				focusIndex = Math.max(0, portfolios.findIndex((p) => p.id === selectedId));
			}
			return;
		}

		switch (e.key) {
			case "ArrowDown":
				e.preventDefault();
				focusIndex = Math.min(focusIndex + 1, portfolios.length - 1);
				break;
			case "ArrowUp":
				e.preventDefault();
				focusIndex = Math.max(focusIndex - 1, 0);
				break;
			case "Enter": {
				e.preventDefault();
				const target = portfolios[focusIndex];
				if (target) select(target);
				break;
			}
			case "Escape":
				e.preventDefault();
				isOpen = false;
				break;
		}
	}

	function stateLabel(state: string): string {
		switch (state) {
			case "draft": return "DRAFT";
			case "constructed": return "CONSTRUCTED";
			case "validated": return "VALIDATED";
			case "approved": return "APPROVED";
			case "live": return "LIVE";
			case "paused": return "PAUSED";
			case "archived": return "ARCHIVED";
			case "rejected": return "REJECTED";
			default: return state.toUpperCase();
		}
	}

	function stateTone(state: string): string {
		switch (state) {
			case "live": return "success";
			case "approved":
			case "validated": return "info";
			case "paused": return "warn";
			case "rejected":
			case "archived": return "muted";
			default: return "neutral";
		}
	}

	function holdingsCount(p: ModelPortfolio): number | null {
		return p.fund_selection_schema?.funds?.length ?? null;
	}
</script>

<div class="pp-root" role="combobox" aria-expanded={isOpen} aria-haspopup="listbox">
	{#if portfolios.length === 0}
		<!-- Empty state -->
		<div class="pp-empty">
			<span class="pp-empty-text">No model portfolios yet</span>
			<button type="button" class="pp-create-btn" onclick={onCreate}>
				+ Create Portfolio
			</button>
		</div>
	{:else}
		<!-- Selected display -->
		<button
			type="button"
			class="pp-trigger"
			onclick={toggle}
			onkeydown={handleKeydown}
			aria-label="Select portfolio"
		>
			<span class="pp-trigger-name">
				{selected?.display_name ?? "Select portfolio"}
			</span>
			{#if selected}
				<span class="pp-trigger-state pp-trigger-state--{stateTone(selected.state)}">
					{stateLabel(selected.state)}
				</span>
			{/if}
			<span class="pp-trigger-chevron" aria-hidden="true">
				{isOpen ? "▴" : "▾"}
			</span>
		</button>

		<!-- Dropdown list -->
		{#if isOpen}
			<div class="pp-dropdown" role="listbox">
				{#each portfolios as p, i (p.id)}
					<button
						type="button"
						class="pp-option"
						class:pp-option--selected={p.id === selectedId}
						class:pp-option--focused={i === focusIndex}
						role="option"
						aria-selected={p.id === selectedId}
						onclick={() => select(p)}
					>
						<div class="pp-option-header">
							<span class="pp-option-name">{p.display_name}</span>
							<span class="pp-option-state pp-option-state--{stateTone(p.state)}">
								{stateLabel(p.state)}
							</span>
						</div>
						<div class="pp-option-meta">
							{#if holdingsCount(p) != null}
								<span>{formatNumber(holdingsCount(p)!, 0)} holdings</span>
							{/if}
							{#if p.created_at}
								<span>Created {formatDateTime(p.created_at)}</span>
							{/if}
						</div>
					</button>
				{/each}

				<button type="button" class="pp-option pp-option--create" onclick={onCreate}>
					+ Create new portfolio
				</button>
			</div>
		{/if}
	{/if}
</div>

<style>
	.pp-root {
		position: relative;
		font-family: var(--terminal-font-mono);
	}

	/* ── Empty state ───────────────────────────── */

	.pp-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-4);
	}

	.pp-empty-text {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.pp-create-btn {
		padding: var(--terminal-space-1) var(--terminal-space-3);
		background: transparent;
		border: 1px solid var(--terminal-status-success);
		color: var(--terminal-status-success);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
	}
	.pp-create-btn:hover {
		background: color-mix(in srgb, var(--terminal-status-success) 10%, transparent);
	}
	.pp-create-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	/* ── Trigger ────────────────────────────────── */

	.pp-trigger {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		width: 100%;
		height: 32px;
		padding: 0 var(--terminal-space-2);
		background: var(--terminal-bg-panel-sunken);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		cursor: pointer;
	}
	.pp-trigger:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.pp-trigger-name {
		flex: 1;
		text-align: left;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.pp-trigger-state {
		font-size: var(--terminal-text-9);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.pp-trigger-state--success { color: var(--terminal-status-success); }
	.pp-trigger-state--info { color: var(--terminal-accent, var(--terminal-accent-amber)); }
	.pp-trigger-state--warn { color: var(--terminal-accent-amber); }
	.pp-trigger-state--muted { color: var(--terminal-fg-muted); }
	.pp-trigger-state--neutral { color: var(--terminal-fg-secondary); }

	.pp-trigger-chevron {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	/* ── Dropdown ───────────────────────────────── */

	.pp-dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		z-index: 100;
		max-height: 240px;
		overflow-y: auto;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		border-top: none;
	}

	.pp-option {
		display: flex;
		flex-direction: column;
		gap: 2px;
		width: 100%;
		padding: var(--terminal-space-2);
		background: transparent;
		border: none;
		border-bottom: 1px solid color-mix(in srgb, var(--terminal-fg-muted) 20%, transparent);
		font-family: var(--terminal-font-mono);
		text-align: left;
		cursor: pointer;
		transition: background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.pp-option:hover,
	.pp-option--focused {
		background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent);
	}
	.pp-option--selected {
		border-left: 2px solid var(--terminal-accent-amber);
	}
	.pp-option:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.pp-option-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.pp-option-name {
		flex: 1;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		font-weight: 600;
	}

	.pp-option-state {
		font-size: var(--terminal-text-9);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.pp-option-state--success { color: var(--terminal-status-success); }
	.pp-option-state--info { color: var(--terminal-accent, var(--terminal-accent-amber)); }
	.pp-option-state--warn { color: var(--terminal-accent-amber); }
	.pp-option-state--muted { color: var(--terminal-fg-muted); }
	.pp-option-state--neutral { color: var(--terminal-fg-secondary); }

	.pp-option-meta {
		display: flex;
		gap: var(--terminal-space-3);
		font-size: var(--terminal-text-9);
		color: var(--terminal-fg-muted);
	}

	.pp-option--create {
		color: var(--terminal-status-success);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		border-bottom: none;
	}
</style>
