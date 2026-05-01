<!--
  Test-only FormField stub. Renders label + children, no styling.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		label?: string;
		required?: boolean;
		children?: Snippet;
	}

	let { label, required, children }: Props = $props();
</script>

<label>
	<span>{label}{#if required}<span aria-hidden="true"> *</span>{/if}</span>
	{@render children?.()}
</label>
