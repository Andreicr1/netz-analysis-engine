<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Props {
		value: "pt" | "en";
		onchange: (lang: string) => void;
		class?: string;
	}

	let { value, onchange, class: className }: Props = $props();
</script>

<div
	class={cn(
		"inline-flex rounded-md border border-(--netz-border)",
		className,
	)}
>
	<button
		class={cn(
			"rounded-l-md px-2.5 py-1 text-xs font-medium transition-colors",
			value === "pt"
				? "bg-(--netz-brand-primary) text-white"
				: "bg-(--netz-surface) text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)",
		)}
		onclick={() => onchange("pt")}
	>
		PT
	</button>
	<button
		class={cn(
			"rounded-r-md px-2.5 py-1 text-xs font-medium transition-colors",
			value === "en"
				? "bg-(--netz-brand-primary) text-white"
				: "bg-(--netz-surface) text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)",
		)}
		onclick={() => onchange("en")}
	>
		EN
	</button>
</div>
