<script lang="ts">
	import { cn } from "../../utils/cn.js";

	interface Props {
		value: "pt" | "en";
		onchange: (lang: string) => void;
		class?: string;
	}

	let { value, onchange, class: className }: Props = $props();
</script>

<div
	class={cn(
		"inline-flex rounded-md border border-(--ii-border)",
		className,
	)}
>
	<button
		class={cn(
			"rounded-l-md px-2.5 py-1 text-xs font-medium transition-colors",
			value === "pt"
				? "bg-(--ii-brand-primary) text-white"
				: "bg-(--ii-surface) text-(--ii-text-secondary) hover:bg-(--ii-surface-alt)",
		)}
		onclick={() => onchange("pt")}
	>
		PT
	</button>
	<button
		class={cn(
			"rounded-r-md px-2.5 py-1 text-xs font-medium transition-colors",
			value === "en"
				? "bg-(--ii-brand-primary) text-white"
				: "bg-(--ii-surface) text-(--ii-text-secondary) hover:bg-(--ii-surface-alt)",
		)}
		onclick={() => onchange("en")}
	>
		EN
	</button>
</div>
