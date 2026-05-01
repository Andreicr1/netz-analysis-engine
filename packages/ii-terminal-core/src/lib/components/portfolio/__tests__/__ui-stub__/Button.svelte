<!--
  Test-only Button stub. Forwards onclick + disabled.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		type?: "button" | "submit" | "reset";
		variant?: string;
		disabled?: boolean;
		onclick?: (e: MouseEvent) => void;
		children?: Snippet;
		[key: string]: unknown;
	}

	let {
		type = "button",
		variant = "default",
		disabled = false,
		onclick,
		children,
		...rest
	}: Props = $props();
</script>

<button {type} {disabled} {onclick} data-variant={variant} {...rest}>
	{@render children?.()}
</button>
