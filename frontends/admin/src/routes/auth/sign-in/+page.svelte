<!--
  Clerk Sign In page for admin panel.
-->
<script lang="ts">
	import { page } from "$app/stores";

	const error = $page.url.searchParams.get("error");
</script>

<div class="flex min-h-screen items-center justify-center bg-[var(--netz-surface)]">
	<div class="w-full max-w-md rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-8 shadow-lg">
		<h1 class="mb-2 text-center text-2xl font-bold text-[var(--netz-text-primary)]">
			Netz Admin
		</h1>
		<p class="mb-6 text-center text-sm text-[var(--netz-text-secondary)]">
			Platform administration panel
		</p>

		{#if error === "unauthorized"}
			<div class="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
				You must be a platform admin to access this panel.
			</div>
		{/if}

		<p class="text-center text-sm text-[var(--netz-text-muted)]">
			Sign in with your Clerk account to continue.
		</p>
	</div>
</div>
