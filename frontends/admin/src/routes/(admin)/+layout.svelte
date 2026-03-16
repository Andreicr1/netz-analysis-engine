<!--
  Admin route group layout — just passes through to children.
  Guard is in +layout.server.ts.
-->
<script lang="ts">
	let { children }: { children: import("svelte").Snippet } = $props();
</script>

{@render children()}
