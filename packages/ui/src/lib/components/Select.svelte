<script lang="ts">
	import { cn } from "../utils/cn.js";
	import { fly } from "svelte/transition";

	interface Option {
		value: string;
		label: string;
	}

	interface Props {
		value?: string;
		onValueChange?: (value: string) => void;
		options: Option[];
		placeholder?: string;
		disabled?: boolean;
		searchable?: boolean;
		class?: string;
	}

	let {
		value = $bindable(""),
		onValueChange,
		options,
		placeholder = "Select...",
		disabled = false,
		searchable = false,
		class: className,
	}: Props = $props();

	let open = $state(false);
	let search = $state("");
	let highlightIndex = $state(-1);
	let triggerEl = $state<HTMLButtonElement | null>(null);
	let dropdownEl = $state<HTMLDivElement | null>(null);
	let searchInputEl = $state<HTMLInputElement | null>(null);

	let filtered = $derived(
		search
			? options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()))
			: options,
	);

	let selectedLabel = $derived(
		options.find((o) => o.value === value)?.label ?? "",
	);

	function select(opt: Option) {
		value = opt.value;
		onValueChange?.(opt.value);
		close();
	}

	function toggle() {
		if (disabled) return;
		if (open) {
			close();
		} else {
			openDropdown();
		}
	}

	function openDropdown() {
		open = true;
		search = "";
		highlightIndex = value ? filtered.findIndex((o) => o.value === value) : 0;
		if (highlightIndex < 0) highlightIndex = 0;
		requestAnimationFrame(() => {
			if (searchable && searchInputEl) searchInputEl.focus();
		});
	}

	function close() {
		open = false;
		search = "";
		highlightIndex = -1;
		triggerEl?.focus();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) {
			if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				openDropdown();
			}
			return;
		}

		switch (e.key) {
			case "ArrowDown":
				e.preventDefault();
				highlightIndex = (highlightIndex + 1) % filtered.length;
				scrollIntoView();
				break;
			case "ArrowUp":
				e.preventDefault();
				highlightIndex = (highlightIndex - 1 + filtered.length) % filtered.length;
				scrollIntoView();
				break;
			case "Enter": {
				e.preventDefault();
				const item = filtered[highlightIndex];
				if (item) select(item);
				break;
			}
			case "Escape":
				e.preventDefault();
				close();
				break;
			case "Tab":
				close();
				break;
		}
	}

	function scrollIntoView() {
		requestAnimationFrame(() => {
			dropdownEl
				?.querySelector(`[data-index="${highlightIndex}"]`)
				?.scrollIntoView({ block: "nearest" });
		});
	}

	function handlePointerDown(e: PointerEvent) {
		if (!open) return;
		const target = e.target as Node;
		if (!triggerEl?.contains(target) && !dropdownEl?.contains(target)) {
			close();
		}
	}

	$effect(() => {
		if (open) {
			document.addEventListener("pointerdown", handlePointerDown, true);
			return () => document.removeEventListener("pointerdown", handlePointerDown, true);
		}
	});
</script>

<div class="netz-select" class:netz-select--open={open}>
	<button
		bind:this={triggerEl}
		type="button"
		class={cn(
			"netz-ui-field netz-select__trigger",
			className,
		)}
		{disabled}
		aria-haspopup="listbox"
		aria-expanded={open}
		onclick={toggle}
		onkeydown={handleKeydown}
	>
		<span class="netz-select__value" class:netz-select__placeholder={!value}>
			{value ? selectedLabel : placeholder}
		</span>
		<svg class="netz-select__chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="m6 9 6 6 6-6"/>
		</svg>
	</button>

	{#if open}
		<div
			bind:this={dropdownEl}
			class="netz-select__dropdown"
			role="listbox"
			transition:fly={{ y: -4, duration: 120 }}
		>
			{#if searchable}
				<div class="netz-select__search-wrap">
					<input
						bind:this={searchInputEl}
						bind:value={search}
						type="text"
						class="netz-select__search"
						placeholder="Search..."
						onkeydown={handleKeydown}
						autocomplete="off"
					/>
				</div>
			{/if}
			{#if filtered.length === 0}
				<div class="netz-select__empty">No results</div>
			{:else}
				{#each filtered as opt, i (opt.value)}
					<button
						type="button"
						class="netz-select__option"
						class:netz-select__option--selected={opt.value === value}
						class:netz-select__option--highlighted={i === highlightIndex}
						data-index={i}
						role="option"
						aria-selected={opt.value === value}
						onclick={() => select(opt)}
						onpointerenter={() => highlightIndex = i}
					>
						{opt.label}
					</button>
				{/each}
			{/if}
		</div>
	{/if}
</div>

<style>
	.netz-select {
		position: relative;
		display: inline-flex;
		width: 100%;
	}

	.netz-select__trigger {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		width: 100%;
		height: var(--netz-space-control-height-md);
		padding: 0 12px 0 14px;
		font-size: 14px;
		letter-spacing: -0.005em;
		color: var(--netz-text-primary);
		cursor: pointer;
		text-align: left;
	}

	.netz-select__trigger:disabled {
		cursor: not-allowed;
		opacity: 0.5;
		background: var(--netz-surface-inset);
	}

	.netz-select__value {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.netz-select__placeholder {
		color: var(--netz-text-muted);
	}

	.netz-select__chevron {
		flex-shrink: 0;
		color: var(--netz-text-muted);
		transition: transform 120ms ease;
	}

	.netz-select--open .netz-select__chevron {
		transform: rotate(180deg);
	}

	.netz-select__dropdown {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		right: 0;
		z-index: 50;
		max-height: 240px;
		overflow-y: auto;
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-md);
		box-shadow: var(--netz-shadow-floating);
		scrollbar-width: thin;
	}

	.netz-select__search-wrap {
		position: sticky;
		top: 0;
		padding: 6px;
		background: var(--netz-surface-elevated);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.netz-select__search {
		width: 100%;
		height: 32px;
		padding: 0 10px;
		font-size: 13px;
		color: var(--netz-text-primary);
		background: var(--netz-surface-inset);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm);
		outline: none;
	}

	.netz-select__search:focus {
		border-color: var(--netz-border-focus);
	}

	.netz-select__option {
		display: block;
		width: 100%;
		padding: 8px 14px;
		font-size: 13px;
		color: var(--netz-text-secondary);
		text-align: left;
		cursor: pointer;
		border: none;
		background: transparent;
	}

	.netz-select__option:hover,
	.netz-select__option--highlighted {
		background: var(--netz-bg-hover);
		color: var(--netz-text-primary);
	}

	.netz-select__option--selected {
		color: var(--netz-text-primary);
		font-weight: 600;
	}

	.netz-select__empty {
		padding: 12px 14px;
		font-size: 13px;
		color: var(--netz-text-muted);
		text-align: center;
	}
</style>
