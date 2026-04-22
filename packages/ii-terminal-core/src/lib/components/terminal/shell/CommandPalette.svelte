<script lang="ts">
	import { getContext } from "svelte";
	import { fade, fly } from "svelte/transition";
	import { goto } from "$app/navigation";
	import { svelteTransitionFor } from "@investintell/ui";
	import { createClientApiClient } from "../../../api/client";
	import {
		closePalette,
		palette,
		setPaletteQuery,
		setPaletteSelectedIndex,
	} from "../../../stores/palette.svelte";

	interface FundSearchResult {
		instrument_id: string;
		name: string;
		ticker: string | null;
		strategy_label: string | null;
		asset_class: string | null;
	}

	interface SearchResponse {
		results: FundSearchResult[];
		latency_ms: number;
		cached: boolean;
	}

	type CommandType = "route" | "fund";

	interface CommandItemBase {
		id: string;
		type: CommandType;
		title: string;
		subtitle?: string;
		keywords: string[];
		onSelect: () => void | Promise<void>;
	}

	interface RouteCommandItem extends CommandItemBase {
		type: "route";
		path: string;
		shortcut: string;
		badge: "ROUTE";
	}

	interface FundCommandItem extends CommandItemBase {
		type: "fund";
		instrumentId: string;
		ticker: string | null;
		strategyLabel: string | null;
		assetClass: string | null;
		badge: "FUND";
	}

	type CommandItem = RouteCommandItem | FundCommandItem;

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let inputEl: HTMLInputElement | undefined = $state();
	let frameEl: HTMLDivElement | undefined = $state();
	let debouncedQuery = $state("");
	let remoteItems = $state<FundCommandItem[]>([]);
	let loading = $state(false);
	let fetchError = $state<string | null>(null);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let activeFetchController: AbortController | null = null;

	async function gotoRoute(path: string) {
		await goto(path);
	}

	async function gotoFundResearch(instrumentId: string) {
		await goto(`/fund/${instrumentId}/research`);
	}

	const STATIC_COMMANDS: ReadonlyArray<RouteCommandItem> = [
		{
			id: "route.screener",
			type: "route",
			title: "Open Screener",
			subtitle: "/screener",
			path: "/screener",
			shortcut: "G S",
			badge: "ROUTE",
			keywords: ["screener", "screen", "funds", "/screener"],
			onSelect: () => gotoRoute("/screener"),
		},
		{
			id: "route.allocation",
			type: "route",
			title: "Open Allocation",
			subtitle: "/allocation",
			path: "/allocation",
			shortcut: "G A",
			badge: "ROUTE",
			keywords: ["allocation", "ips", "portfolio", "/allocation"],
			onSelect: () => gotoRoute("/allocation"),
		},
		{
			id: "route.live",
			type: "route",
			title: "Open Live Workbench",
			subtitle: "/live",
			path: "/live",
			shortcut: "G L",
			badge: "ROUTE",
			keywords: ["live", "watchlist", "trading", "/live"],
			onSelect: () => gotoRoute("/live"),
		},
	];

	const localItems = $derived.by<RouteCommandItem[]>(() => {
		const normalized = palette.query.trim().toLowerCase();
		if (!normalized) {
			return [...STATIC_COMMANDS];
		}
		return STATIC_COMMANDS.filter((item) =>
			[item.title, item.subtitle ?? "", item.shortcut, ...item.keywords]
				.join(" ")
				.toLowerCase()
				.includes(normalized),
		);
	});

	const items = $derived.by<CommandItem[]>(() => [...localItems, ...remoteItems]);

	$effect(() => {
		if (!palette.isOpen) {
			if (debounceTimer) clearTimeout(debounceTimer);
			activeFetchController?.abort();
			debouncedQuery = "";
			remoteItems = [];
			loading = false;
			fetchError = null;
			return;
		}

		const nextQuery = palette.query.trim();
		if (debounceTimer) clearTimeout(debounceTimer);

		if (nextQuery.length < 2) {
			debouncedQuery = nextQuery;
			activeFetchController?.abort();
			remoteItems = [];
			loading = false;
			fetchError = null;
			return;
		}

		debounceTimer = setTimeout(() => {
			debouncedQuery = nextQuery;
		}, 180);

		return () => {
			if (debounceTimer) clearTimeout(debounceTimer);
		};
	});

	$effect(() => {
		if (!palette.isOpen) return;
		const q = debouncedQuery;
		if (q.length < 2) return;

		activeFetchController?.abort();
		const controller = new AbortController();
		activeFetchController = controller;
		loading = true;
		fetchError = null;

		void loadRemoteItems(q, controller);

		return () => {
			controller.abort();
			if (activeFetchController === controller) {
				activeFetchController = null;
			}
		};
	});

	$effect(() => {
		if (!palette.isOpen) return;
		if (typeof document === "undefined") return;

		const previousOverflow = document.body.style.overflow;
		const previousFocused = document.activeElement as HTMLElement | null;
		document.body.style.overflow = "hidden";

		queueMicrotask(() => {
			inputEl?.focus({ preventScroll: true });
			inputEl?.select();
		});

		return () => {
			document.body.style.overflow = previousOverflow;
			previousFocused?.focus?.({ preventScroll: true });
		};
	});

	$effect(() => {
		if (items.length === 0) {
			setPaletteSelectedIndex(0);
			return;
		}
		if (palette.selectedIndex >= items.length) {
			setPaletteSelectedIndex(items.length - 1);
		}
	});

	$effect(() => {
		if (!palette.isOpen || items.length === 0) return;
		const activeItem = items[palette.selectedIndex];
		if (!activeItem) return;
		queueMicrotask(() => {
			document.getElementById(optionIdFor(activeItem.id))?.scrollIntoView({
				block: "nearest",
			});
		});
	});

	async function loadRemoteItems(q: string, controller: AbortController) {
		try {
			const response = await api.get<SearchResponse>(
				"/search",
				{ q, limit: 8 },
				{ signal: controller.signal },
			);
			if (controller.signal.aborted) return;
			remoteItems = response.results.map((item) => ({
				id: `fund.${item.instrument_id}`,
				type: "fund",
				title: item.name,
				subtitle: [item.ticker, item.strategy_label, item.asset_class]
					.filter(Boolean)
					.join(" · "),
				instrumentId: item.instrument_id,
				ticker: item.ticker,
				strategyLabel: item.strategy_label,
				assetClass: item.asset_class,
				badge: "FUND",
				keywords: [
					item.name,
					item.ticker ?? "",
					item.strategy_label ?? "",
					item.asset_class ?? "",
				],
				onSelect: () => gotoFundResearch(item.instrument_id),
			}));
		} catch (error: unknown) {
			if (error instanceof DOMException && error.name === "AbortError") return;
			remoteItems = [];
			fetchError = error instanceof Error ? error.message : "Search failed.";
		} finally {
			if (activeFetchController === controller) {
				loading = false;
				activeFetchController = null;
			}
		}
	}

	function handleBackdropClick(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			closePalette();
		}
	}

	function handleFrameClick(event: MouseEvent) {
		event.stopPropagation();
	}

	function handleInput(event: Event) {
		setPaletteQuery((event.currentTarget as HTMLInputElement).value);
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === "Escape") {
			event.preventDefault();
			closePalette();
			return;
		}

		if (event.key === "Tab") {
			event.preventDefault();
			inputEl?.focus({ preventScroll: true });
			return;
		}

		if (event.key === "ArrowDown") {
			event.preventDefault();
			if (items.length === 0) return;
			setPaletteSelectedIndex((palette.selectedIndex + 1) % items.length);
			return;
		}

		if (event.key === "ArrowUp") {
			event.preventDefault();
			if (items.length === 0) return;
			setPaletteSelectedIndex((palette.selectedIndex - 1 + items.length) % items.length);
			return;
		}

		if (event.key === "Enter") {
			event.preventDefault();
			void selectItem(items[palette.selectedIndex]);
		}
	}

	async function selectItem(item: CommandItem | undefined) {
		if (!item) return;
		try {
			await item.onSelect();
			closePalette();
		} catch {
			// Keep the palette open if navigation fails so the user can retry.
		}
	}

	function handleOptionClick(index: number) {
		setPaletteSelectedIndex(index);
		void selectItem(items[index]);
	}

	function handleOptionMouseEnter(index: number) {
		setPaletteSelectedIndex(index);
	}

	function optionIdFor(id: string) {
		return `terminal-command-palette-option-${id}`;
	}

	const listboxId = "terminal-command-palette-listbox";
	const inputId = "terminal-command-palette-input";
	const helperId = "terminal-command-palette-helper";
	const activeDescendantId = $derived(
		items[palette.selectedIndex]?.id
			? optionIdFor(items[palette.selectedIndex]!.id)
			: undefined,
	);
</script>

{#if palette.isOpen}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div
		class="cp-backdrop"
		role="presentation"
		onclick={handleBackdropClick}
		transition:fade={svelteTransitionFor("chrome", { duration: "tick" })}
	>
		<div
			bind:this={frameEl}
			class="cp-frame"
			role="dialog"
			aria-modal="true"
			aria-label="Command palette"
			tabindex="-1"
			onclick={handleFrameClick}
			onkeydown={handleKeydown}
			in:fly={{ y: -12, ...svelteTransitionFor("chrome", { duration: "tick" }) }}
		>
			<header class="cp-header">
				<span class="cp-prompt">⌘</span>
				<input
					bind:this={inputEl}
					id={inputId}
					class="cp-input"
					type="text"
					value={palette.query}
					placeholder="Search funds or jump to a route..."
					autocomplete="off"
					autocorrect="off"
					autocapitalize="off"
					spellcheck="false"
					role="combobox"
					aria-autocomplete="list"
					aria-expanded="true"
					aria-controls={listboxId}
					aria-describedby={helperId}
					aria-activedescendant={activeDescendantId}
					oninput={handleInput}
				/>
			</header>

			<ul id={listboxId} class="cp-list" role="listbox" aria-busy={loading}>
				{#each items as item, index (item.id)}
					{@const isSelected = index === palette.selectedIndex}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<li
						id={optionIdFor(item.id)}
						class="cp-option"
						class:cp-option--highlighted={isSelected}
						role="option"
						aria-selected={isSelected}
						onclick={() => handleOptionClick(index)}
						onmouseenter={() => handleOptionMouseEnter(index)}
					>
						<div class="cp-option-copy">
							<span class="cp-option-label">{item.title}</span>
							{#if item.subtitle}
								<span class="cp-option-subtitle">{item.subtitle}</span>
							{/if}
						</div>
						<div class="cp-option-meta">
							<span class="cp-option-badge">{item.badge}</span>
							{#if item.type === "route"}
								<span class="cp-option-hint">{item.shortcut}</span>
							{/if}
						</div>
					</li>
				{:else}
					<li class="cp-empty">
						{#if loading}
							Searching funds…
						{:else if fetchError}
							{fetchError}
						{:else if palette.query.trim().length >= 2}
							No matches for "{palette.query.trim()}"
						{:else}
							Type 2+ characters to search funds. Route shortcuts appear instantly.
						{/if}
					</li>
				{/each}
			</ul>

			<footer id={helperId} class="cp-footer">
				<span class="cp-footer-count">{items.length} results</span>
				<span class="cp-footer-keys">↑↓ navigate · Enter select · Esc close</span>
			</footer>
		</div>
	</div>
{/if}

<style>
	.cp-backdrop {
		position: fixed;
		inset: 0;
		z-index: var(--terminal-z-palette);
		display: grid;
		place-items: start center;
		padding: 12vh var(--terminal-space-4) 0;
		background: var(--terminal-bg-scrim);
		backdrop-filter: blur(6px);
		-webkit-backdrop-filter: blur(6px);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
	}

	.cp-frame {
		width: min(720px, 100%);
		max-height: min(68vh, 640px);
		display: grid;
		grid-template-rows: auto 1fr auto;
		overflow: hidden;
		background:
			linear-gradient(180deg, color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent), transparent 24%),
			var(--terminal-bg-void);
		border: var(--terminal-border-hairline);
		box-shadow: 0 24px 90px rgba(0, 0, 0, 0.45);
	}

	.cp-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-4);
		border-bottom: var(--terminal-border-hairline);
		background: color-mix(in srgb, var(--terminal-bg-panel) 92%, black);
	}

	.cp-prompt {
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-14);
		font-weight: 700;
	}

	.cp-input {
		flex: 1;
		border: none;
		outline: none;
		background: transparent;
		color: var(--terminal-fg-primary);
		font-family: inherit;
		font-size: var(--terminal-text-14);
	}

	.cp-input::placeholder {
		color: var(--terminal-fg-tertiary);
	}

	.cp-list {
		min-height: 0;
		margin: 0;
		padding: var(--terminal-space-2) 0;
		list-style: none;
		overflow-y: auto;
	}

	.cp-option {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-4);
		padding: var(--terminal-space-3) var(--terminal-space-4);
		cursor: pointer;
		border-left: 2px solid transparent;
	}

	.cp-option--highlighted {
		background: var(--terminal-bg-panel-raised);
		border-left-color: var(--terminal-accent-cyan);
	}

	.cp-option-copy {
		display: flex;
		flex-direction: column;
		min-width: 0;
		gap: 4px;
	}

	.cp-option-label {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--terminal-fg-primary);
	}

	.cp-option-subtitle {
		font-size: var(--terminal-text-10);
		letter-spacing: 0.04em;
		color: var(--terminal-fg-tertiary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.cp-option-meta {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
		flex-shrink: 0;
	}

	.cp-option-badge,
	.cp-option-hint {
		padding: 2px 6px;
		font-size: var(--terminal-text-10);
		letter-spacing: 0.08em;
		color: var(--terminal-fg-tertiary);
		border: 1px solid var(--terminal-fg-muted);
	}

	.cp-empty {
		padding: var(--terminal-space-7) var(--terminal-space-4);
		text-align: center;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		letter-spacing: 0.05em;
	}

	.cp-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-4);
		padding: var(--terminal-space-3) var(--terminal-space-4);
		border-top: var(--terminal-border-hairline);
		background: color-mix(in srgb, var(--terminal-bg-panel) 92%, black);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: 0.08em;
	}

	@media (max-width: 640px) {
		.cp-backdrop {
			padding-top: 8vh;
		}

		.cp-frame {
			max-height: 78vh;
		}

		.cp-option {
			padding-inline: var(--terminal-space-3);
		}

		.cp-footer {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
