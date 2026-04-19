<script lang="ts">
	import Pill from "./Pill.svelte";

	export type Density = "standard" | "compact";

	interface Props {
		value: Density;
		onChange: (v: Density) => void;
		class?: string;
	}

	let { value, onChange, class: className }: Props = $props();

	const options: { label: string; val: Density }[] = [
		{ label: "STANDARD", val: "standard" },
		{ label: "COMPACT", val: "compact" },
	];
</script>

<div class="terminal-density-toggle {className ?? ''}" role="radiogroup" aria-label="Density">
	{#each options as opt (opt.val)}
		<Pill
			as="button"
			label={opt.label}
			tone={value === opt.val ? "accent" : "neutral"}
			pressed={value === opt.val}
			onclick={() => onChange(opt.val)}
			ariaLabel={`Density ${opt.label}`}
		/>
	{/each}
</div>

<style>
	.terminal-density-toggle {
		display: inline-flex;
		gap: var(--terminal-space-1);
	}
</style>
