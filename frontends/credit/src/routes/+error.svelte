<!--
  Error page — shows appropriate error UI based on HTTP status.
-->
<script lang="ts">
	import { page } from "$app/state";
	import { BackendUnavailable } from "@netz/ui";
</script>

{#if page.status >= 500}
	<BackendUnavailable />
{:else}
	{@const status = page.status}
	{@const messages: Record<number, { title: string; detail: string }> = {
		403: { title: "Access Denied", detail: "You don't have permission to access this page." },
		404: { title: "Page Not Found", detail: "Page not found." }
	}}
	{@const info = messages[status] ?? { title: "Something went wrong", detail: page.error?.message ?? "Something went wrong." }}

	<div class="flex h-full items-center justify-center">
		<div class="text-center">
			<h1 class="mb-2 text-4xl font-bold text-(--netz-text-primary)">{status}</h1>
			<p class="text-(--netz-text-secondary)">{info.detail}</p>
			<a
				href="/"
				class="mt-4 inline-block rounded-md bg-(--netz-brand-primary) px-4 py-2 text-sm text-white hover:opacity-90"
			>
				Go to Dashboard
			</a>
		</div>
	</div>
{/if}
