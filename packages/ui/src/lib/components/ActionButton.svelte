<script lang="ts">
	import { cn } from "../utils/cn.js";
	import Button from "./Button.svelte";
	import type { Snippet } from "svelte";
	import type { HTMLButtonAttributes } from "svelte/elements";

	type Variant = "default" | "secondary" | "destructive" | "outline" | "ghost";
	type Size = "sm" | "default" | "lg";

	interface Props extends HTMLButtonAttributes {
		variant?: Variant;
		size?: Size;
		loading?: boolean;
		loadingText?: string;
		children?: Snippet;
	}

	let {
		variant = "default",
		size = "default",
		loading = false,
		loadingText,
		class: className,
		children,
		...rest
	}: Props = $props();
</script>

<Button
	{variant}
	{size}
	class={className}
	disabled={loading || rest.disabled}
	{...rest}
>
	{#if loading}
		<svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
			<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
			<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
		</svg>
		{loadingText ?? ""}
	{:else}
		{@render children?.()}
	{/if}
</Button>
