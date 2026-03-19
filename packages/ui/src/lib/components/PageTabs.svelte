<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface TabDef {
		value?: string;
		id?: string;
		label: string;
	}

	interface Props {
		tabs: TabDef[];
		/** Initial tab for uncontrolled mode (uses URL ?tab= sync) */
		defaultTab?: string;
		/** Current tab for controlled mode (caller manages state) */
		active?: string;
		/** Callback when tab changes (controlled mode) */
		onChange?: (tab: string) => void;
		class?: string;
		children?: Snippet<[string]>;
	}

	let { tabs, defaultTab, active, onChange, class: className, children }: Props = $props();

	/** Resolve the identifier for a tab definition */
	function resolveTabValue(tab: TabDef): string {
		return tab.value ?? tab.id ?? tab.label;
	}

	/** Read ?tab= from current URL, fallback to defaultTab */
	function getInitialTab(): string {
		const firstTab = tabs[0];
		const fallback = defaultTab ?? (firstTab ? resolveTabValue(firstTab) : "");
		if (typeof window === "undefined") return fallback;
		const params = new URLSearchParams(window.location.search);
		return params.get("tab") ?? fallback;
	}

	let internalTab = $state(getInitialTab());

	/** The effective active tab — controlled (active prop) or uncontrolled (internal) */
	let currentTab = $derived(active ?? internalTab);

	function select(value: string) {
		if (onChange) {
			onChange(value);
		} else {
			internalTab = value;
			// Sync URL without navigation (uncontrolled mode only)
			if (typeof window !== "undefined") {
				const url = new URL(window.location.href);
				url.searchParams.set("tab", value);
				window.history.replaceState({}, "", url.toString());
			}
		}
	}
</script>

<div class={cn("w-full", className)}>
	<!-- Tab triggers -->
	<div
		class="flex items-center gap-6 overflow-x-auto border-b border-(--netz-border-subtle)"
		role="tablist"
	>
		{#each tabs as tab}
			{@const tabValue = resolveTabValue(tab)}
			<button
				role="tab"
				aria-selected={currentTab === tabValue}
				class={cn(
					"relative flex shrink-0 items-center gap-2 px-1 pb-3 pt-1 text-sm font-medium tracking-[-0.01em] transition-[color,box-shadow] duration-(--netz-duration-fast) focus-visible:outline-none focus-visible:shadow-(--netz-shadow-focus)",
					currentTab === tabValue
						? "text-(--netz-text-primary)"
						: "text-(--netz-text-muted) hover:text-(--netz-text-secondary)",
				)}
				onclick={() => select(tabValue)}
			>
				{tab.label}
				{#if currentTab === tabValue}
					<span
						class="absolute bottom-0 left-0 right-0 h-px bg-(--netz-border-accent)"
					></span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Tab content -->
	<div class="mt-4" role="tabpanel">
		{@render children?.(currentTab)}
	</div>
</div>
