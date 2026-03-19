<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface TabDef {
		value: string;
		label: string;
	}

	interface Props {
		tabs: TabDef[];
		defaultTab: string;
		class?: string;
		children?: Snippet<[string]>;
	}

	let { tabs, defaultTab, class: className, children }: Props = $props();

	/** Read ?tab= from current URL, fallback to defaultTab */
	function getInitialTab(): string {
		if (typeof window === "undefined") return defaultTab;
		const params = new URLSearchParams(window.location.search);
		return params.get("tab") ?? defaultTab;
	}

	let activeTab = $state(getInitialTab());

	function select(value: string) {
		activeTab = value;
		// Sync URL without navigation
		if (typeof window !== "undefined") {
			const url = new URL(window.location.href);
			url.searchParams.set("tab", value);
			window.history.replaceState({}, "", url.toString());
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
			<button
				role="tab"
				aria-selected={activeTab === tab.value}
				class={cn(
					"relative flex shrink-0 items-center gap-2 px-1 pb-3 pt-1 text-sm font-medium tracking-[-0.01em] transition-[color,box-shadow] duration-(--netz-duration-fast) focus-visible:outline-none focus-visible:shadow-(--netz-shadow-focus)",
					activeTab === tab.value
						? "text-(--netz-text-primary)"
						: "text-(--netz-text-muted) hover:text-(--netz-text-secondary)",
				)}
				onclick={() => select(tab.value)}
			>
				{tab.label}
				{#if activeTab === tab.value}
					<span
						class="absolute bottom-0 left-0 right-0 h-px bg-(--netz-border-accent)"
					></span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Tab content -->
	<div class="mt-4" role="tabpanel">
		{@render children?.(activeTab)}
	</div>
</div>
