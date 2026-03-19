<script lang="ts">
	import { goto } from "$app/navigation";
	import { onMount } from "svelte";

	onMount(() => {
		goto("/health");
	});
</script>

<div class="flex h-full items-center justify-center">
	<p class="text-(--netz-text-muted)">Redirecting...</p>
</div>
