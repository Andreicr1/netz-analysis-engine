<!--
  Sign-in page — Clerk UI will be mounted here.
  Admin guard: only org:admin users can access the admin panel.
-->
<script lang="ts">
	const DEV_MODE = import.meta.env.DEV;
</script>

<div class="flex min-h-screen items-center justify-center bg-[var(--netz-surface-alt)]">
	<div class="w-full max-w-md rounded-lg bg-white p-8 shadow-lg">
		<div class="mb-6 text-center">
			<h1 class="text-2xl font-bold text-[var(--netz-navy,#1b365d)]">Netz Admin</h1>
			<p class="mt-2 text-sm text-[var(--netz-text-secondary)]">Admin access required to continue</p>
		</div>

		{#if DEV_MODE}
			<div class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4">
				<p class="mb-3 text-xs font-medium text-[var(--netz-text-muted)]">Development Mode</p>
				<a
					href="/"
					class="block w-full rounded-md bg-[var(--netz-primary,#1b365d)] px-4 py-2.5 text-center text-sm font-medium text-white hover:opacity-90"
				>
					Continue as Dev Admin
				</a>
			</div>
		{:else}
			<!-- svelte-clerk SignIn component will be mounted here -->
			<div id="clerk-sign-in" class="flex justify-center">
				<p class="text-sm text-[var(--netz-text-muted)]">Loading authentication...</p>
			</div>
		{/if}
	</div>
</div>
