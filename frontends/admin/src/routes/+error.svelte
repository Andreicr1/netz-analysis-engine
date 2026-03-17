<!--
  Error page — shows appropriate error UI based on HTTP status.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { BackendUnavailable } from "@netz/ui";
</script>

{#if $page.status >= 500}
	<BackendUnavailable />
{:else if $page.status === 403}
	<div class="flex h-full items-center justify-center">
		<div class="text-center">
			<h1 class="mb-2 text-4xl font-bold text-[var(--netz-text-primary)]">403</h1>
			<p class="text-[var(--netz-text-secondary)]">You don't have permission to access this page.</p>
			<a
				href="/auth/sign-in"
				class="mt-4 inline-block rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm text-white hover:opacity-90"
			>
				Sign In
			</a>
		</div>
	</div>
{:else if $page.status === 404}
	<div class="flex h-full items-center justify-center">
		<div class="text-center">
			<h1 class="mb-2 text-4xl font-bold text-[var(--netz-text-primary)]">404</h1>
			<p class="text-[var(--netz-text-secondary)]">Page not found.</p>
			<a
				href="/health"
				class="mt-4 inline-block rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm text-white hover:opacity-90"
			>
				Go to Dashboard
			</a>
		</div>
	</div>
{:else}
	<div class="flex h-full items-center justify-center">
		<div class="text-center">
			<h1 class="mb-2 text-4xl font-bold text-[var(--netz-text-primary)]">{$page.status}</h1>
			<p class="text-[var(--netz-text-secondary)]">{$page.error?.message ?? "Something went wrong."}</p>
			<a
				href="/health"
				class="mt-4 inline-block rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm text-white hover:opacity-90"
			>
				Go to Dashboard
			</a>
		</div>
	</div>
{/if}
