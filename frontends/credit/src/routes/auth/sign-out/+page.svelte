<!--
  Sign-out page — clears session and redirects to sign-in.
-->
<script lang="ts">
	import { onMount } from "svelte";

	onMount(() => {
		window.location.href = "https://accounts.investintell.com/sign-in";
	});
</script>

<div class="flex min-h-screen items-center justify-center bg-(--netz-surface-alt)">
	<p class="text-sm text-(--netz-text-secondary)">Signing out...</p>
</div>
