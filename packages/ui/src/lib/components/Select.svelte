<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Option {
		value: string;
		label: string;
	}

	interface Props {
		value?: string;
		onValueChange?: (value: string) => void;
		options: Option[];
		placeholder?: string;
		disabled?: boolean;
		class?: string;
	}

	let {
		value = $bindable(""),
		onValueChange,
		options,
		placeholder = "Select...",
		disabled = false,
		class: className,
	}: Props = $props();

	function handleChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		value = target.value;
		onValueChange?.(target.value);
	}
</script>

<select
	class={cn(
		"netz-ui-field flex h-[var(--netz-space-control-height-md)] w-full appearance-none rounded-[var(--netz-radius-md)] px-3.5 py-2 pr-10 text-sm tracking-[-0.005em] text-[var(--netz-text-primary)] disabled:cursor-not-allowed disabled:bg-[var(--netz-surface-inset)] disabled:opacity-50",
		className,
	)}
	{disabled}
	{value}
	onchange={handleChange}
>
	{#if placeholder}
		<option value="" disabled selected={!value}>{placeholder}</option>
	{/if}
	{#each options as opt}
		<option value={opt.value} selected={opt.value === value}>{opt.label}</option>
	{/each}
</select>
