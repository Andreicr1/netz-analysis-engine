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
		"flex h-9 w-full appearance-none rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50",
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
