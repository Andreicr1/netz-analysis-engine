<!--
  Sign-out page — clears session and redirects to sign-in.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { onMount } from "svelte";

	onMount(() => {
		// Clerk sign-out will be handled here in production.
		// For now, redirect to sign-in.
		goto("/auth/sign-in");
	});
</script>

<div class="flex min-h-screen items-center justify-center bg-(--netz-surface-alt)">
	<p class="text-sm text-(--netz-text-secondary)">Signing out...</p>
</div>
