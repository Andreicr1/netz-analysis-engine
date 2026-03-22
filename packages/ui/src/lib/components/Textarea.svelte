<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { HTMLTextareaAttributes } from "svelte/elements";

	interface Props extends HTMLTextareaAttributes {
		value?: string;
		class?: string;
		maxLength?: number;
		error?: string;
	}

	let { value = $bindable(""), class: className, maxLength, error, ...rest }: Props = $props();
</script>

<div class="w-full">
	<textarea
		class={cn(
			"netz-ui-field flex min-h-28 w-full rounded-(--netz-radius-md) px-3.5 py-2.5 text-sm leading-6 tracking-[-0.005em] text-(--netz-text-primary) placeholder:text-(--netz-text-muted) disabled:cursor-not-allowed disabled:bg-(--netz-surface-inset) disabled:opacity-50",
			error && "border-(--netz-danger)",
			className,
		)}
		{value}
		maxlength={maxLength}
		{...rest}
	></textarea>
	<div class="mt-1 flex justify-between">
		{#if error}
			<p class="text-xs text-(--netz-danger)">{error}</p>
		{/if}
		{#if maxLength}
			<p class="ml-auto text-xs text-(--netz-text-muted)">{(value ?? "").length}/{maxLength}</p>
		{/if}
	</div>
</div>
