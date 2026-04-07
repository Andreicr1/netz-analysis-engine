<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import * as ToggleGroup from "$lib/components/ui/toggle-group";

	interface Props {
		periods: string[];
		selected: string;
		onSelect: (period: string) => void;
		class?: string;
	}

	let { periods, selected, onSelect, class: className }: Props = $props();
</script>

<ToggleGroup.Root
	type="single"
	value={selected}
	onValueChange={(v) => { if (v) onSelect(v); }}
	class={cn("gap-1 rounded-lg border border-(--ii-border) bg-(--ii-surface-alt) p-1", className)}
	aria-label="Selecionar período"
>
	{#each periods as period (period)}
		<ToggleGroup.Item
			value={period}
			class={cn(
				"rounded-md px-2.5 py-1 text-xs font-medium data-[state=on]:bg-(--ii-brand-primary) data-[state=on]:text-white data-[state=on]:shadow-sm",
				"text-(--ii-text-muted) hover:bg-(--ii-surface) hover:text-(--ii-text-secondary)",
			)}
		>
			{period}
		</ToggleGroup.Item>
	{/each}
</ToggleGroup.Root>
