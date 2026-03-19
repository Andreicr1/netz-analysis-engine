<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Props {
		periods: string[];
		selected: string;
		onSelect: (period: string) => void;
		class?: string;
	}

	let { periods, selected, onSelect, class: className }: Props = $props();
</script>

<div
	class={cn(
		"inline-flex items-center gap-1 rounded-lg border border-(--netz-border) bg-(--netz-surface-alt) p-1",
		className,
	)}
	role="group"
	aria-label="Selecionar período"
>
	{#each periods as period (period)}
		<button
			type="button"
			class={cn(
				"rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
				period === selected
					? "bg-(--netz-brand-primary) text-white shadow-sm"
					: "text-(--netz-text-muted) hover:bg-(--netz-surface) hover:text-(--netz-text-secondary)",
			)}
			aria-pressed={period === selected}
			onclick={() => onSelect(period)}
		>
			{period}
		</button>
	{/each}
</div>
