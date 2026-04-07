<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import * as Tabs from "$lib/components/ui/tabs";

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

	function handleValueChange(value: string) {
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
	<Tabs.Root value={currentTab} onValueChange={handleValueChange}>
		<Tabs.List variant="line" class="w-full justify-start gap-6">
			{#each tabs as tab (resolveTabValue(tab))}
				<Tabs.Trigger value={resolveTabValue(tab)}>
					{tab.label}
				</Tabs.Trigger>
			{/each}
		</Tabs.List>
	</Tabs.Root>

	<!-- Tab content via render prop — preserves external API -->
	<div class="mt-4" role="tabpanel">
		{@render children?.(currentTab)}
	</div>
</div>
