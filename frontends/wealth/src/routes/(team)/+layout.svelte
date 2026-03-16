<!-- Team layout — pass-through for team route group. -->
<script lang="ts">
	import type { Snippet } from "svelte";
	let { children }: { children: Snippet } = $props();
</script>

{@render children()}
