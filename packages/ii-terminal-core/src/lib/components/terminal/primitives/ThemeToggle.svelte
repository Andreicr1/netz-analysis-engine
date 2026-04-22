<script lang="ts">
	import Pill from "./Pill.svelte";

	export type TerminalTheme = "dark" | "light";

	interface Props {
		value: TerminalTheme;
		onChange: (v: TerminalTheme) => void;
		class?: string;
	}

	let { value, onChange, class: className }: Props = $props();

	const options: { label: string; val: TerminalTheme }[] = [
		{ label: "DARK", val: "dark" },
		{ label: "LIGHT", val: "light" },
	];
</script>

<div class="terminal-theme-toggle {className ?? ''}" role="radiogroup" aria-label="Theme">
	{#each options as opt (opt.val)}
		<Pill
			as="button"
			label={opt.label}
			tone={value === opt.val ? "accent" : "neutral"}
			pressed={value === opt.val}
			onclick={() => onChange(opt.val)}
			ariaLabel={`Theme ${opt.label}`}
		/>
	{/each}
</div>

<style>
	.terminal-theme-toggle {
		display: inline-flex;
		gap: var(--terminal-space-1);
	}
</style>
