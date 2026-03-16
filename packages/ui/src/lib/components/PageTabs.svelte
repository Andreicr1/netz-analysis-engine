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
		class="flex border-b border-[var(--netz-border)]"
		role="tablist"
	>
		{#each tabs as tab}
			<button
				role="tab"
				aria-selected={activeTab === tab.value}
				class={cn(
					"relative px-4 py-2.5 text-sm font-medium transition-colors",
					activeTab === tab.value
						? "text-[var(--netz-brand-primary)]"
						: "text-[var(--netz-text-muted)] hover:text-[var(--netz-text-secondary)]",
				)}
				onclick={() => select(tab.value)}
			>
				{tab.label}
				{#if activeTab === tab.value}
					<span
						class="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--netz-brand-primary)]"
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
