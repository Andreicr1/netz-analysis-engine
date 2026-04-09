<!--
  PortfolioDropdown — compact listbox replacing the old sidebar.

  A single button showing the selected portfolio name + chevron.
  Clicking opens a popover listing all available portfolios.
  Full keyboard navigation: ArrowDown/Up to move, Enter to select,
  Escape to close. Click-outside dismisses.

  44px header budget: the trigger button is 28px tall, leaving 8px
  vertical breathing room in the header strip.
-->
<script lang="ts">
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	interface Props {
		portfolios: readonly ModelPortfolio[];
		selected: ModelPortfolio | null;
		onSelect: (portfolio: ModelPortfolio) => void;
	}

	let { portfolios, selected, onSelect }: Props = $props();

	let open = $state(false);
	let focusIndex = $state(-1);
	let triggerEl: HTMLButtonElement | undefined = $state();
	let listEl: HTMLUListElement | undefined = $state();

	function toggle() {
		open = !open;
		if (open) {
			focusIndex = selected
				? portfolios.findIndex((p) => p.id === selected.id)
				: 0;
		}
	}

	function close() {
		open = false;
		triggerEl?.focus();
	}

	function selectItem(p: ModelPortfolio) {
		onSelect(p);
		close();
	}

	function handleTriggerKeydown(e: KeyboardEvent) {
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			if (!open) {
				open = true;
				focusIndex = e.key === "ArrowDown" ? 0 : portfolios.length - 1;
			}
		}
	}

	function handleListKeydown(e: KeyboardEvent) {
		const len = portfolios.length;
		if (!len) return;

		switch (e.key) {
			case "ArrowDown":
				e.preventDefault();
				focusIndex = (focusIndex + 1) % len;
				break;
			case "ArrowUp":
				e.preventDefault();
				focusIndex = (focusIndex - 1 + len) % len;
				break;
			case "Enter":
			case " ":
				e.preventDefault();
				if (focusIndex >= 0 && focusIndex < len) {
					selectItem(portfolios[focusIndex]!);
				}
				break;
			case "Escape":
				e.preventDefault();
				close();
				break;
			case "Home":
				e.preventDefault();
				focusIndex = 0;
				break;
			case "End":
				e.preventDefault();
				focusIndex = len - 1;
				break;
		}
	}

	// Scroll focused item into view
	$effect(() => {
		if (!open || focusIndex < 0 || !listEl) return;
		const item = listEl.children[focusIndex] as HTMLElement | undefined;
		item?.scrollIntoView({ block: "nearest" });
	});

	// Click-outside
	function handleWindowClick(e: MouseEvent) {
		if (!open) return;
		const target = e.target as Node;
		if (triggerEl?.contains(target) || listEl?.contains(target)) return;
		close();
	}
</script>

<svelte:window onclick={handleWindowClick} />

<div class="pd-root">
	<button
		bind:this={triggerEl}
		type="button"
		class="pd-trigger"
		aria-haspopup="listbox"
		aria-expanded={open}
		onclick={toggle}
		onkeydown={handleTriggerKeydown}
	>
		<span class="pd-name">{selected?.display_name ?? "Select portfolio"}</span>
		<span class="pd-chevron" aria-hidden="true">{open ? "\u25B4" : "\u25BE"}</span>
	</button>

	{#if open}
		<ul
			bind:this={listEl}
			class="pd-list"
			role="listbox"
			aria-label="Portfolios"
			tabindex="-1"
			onkeydown={handleListKeydown}
		>
			{#each portfolios as p, i}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
			<li
					role="option"
					class="pd-item"
					class:pd-item--focused={i === focusIndex}
					class:pd-item--selected={p.id === selected?.id}
					aria-selected={p.id === selected?.id}
					onclick={() => selectItem(p)}
				>
					<span class="pd-item-name">{p.display_name}</span>
					<span class="pd-item-profile">{p.profile}</span>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.pd-root {
		position: relative;
	}

	.pd-trigger {
		appearance: none;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 28px;
		padding: 0 10px;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
		font-weight: 600;
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid rgba(255, 255, 255, 0.10);
		cursor: pointer;
		white-space: nowrap;
		max-width: 220px;
		overflow: hidden;
		transition: border-color 80ms, background 80ms;
	}
	.pd-trigger:hover {
		border-color: rgba(255, 255, 255, 0.20);
		background: rgba(255, 255, 255, 0.06);
	}
	.pd-trigger:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 1px;
	}

	.pd-name {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.pd-chevron {
		flex-shrink: 0;
		font-size: 9px;
		color: #5a6577;
	}

	/* ── Popover list ──────────────────────────────────────── */
	.pd-list {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		z-index: 100;
		min-width: 220px;
		max-width: 320px;
		max-height: 280px;
		overflow-y: auto;
		margin: 0;
		padding: 4px 0;
		list-style: none;
		background: #0e1320;
		border: 1px solid rgba(255, 255, 255, 0.12);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
	}

	.pd-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 6px 12px;
		cursor: pointer;
		transition: background 60ms;
	}
	.pd-item:hover,
	.pd-item--focused {
		background: rgba(45, 126, 247, 0.10);
	}
	.pd-item--selected {
		color: #2d7ef7;
	}

	.pd-item-name {
		font-size: 12px;
		font-weight: 500;
		color: #c8d0dc;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.pd-item--selected .pd-item-name {
		color: #2d7ef7;
		font-weight: 600;
	}

	.pd-item-profile {
		flex-shrink: 0;
		font-size: 10px;
		font-weight: 500;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #5a6577;
	}
</style>
