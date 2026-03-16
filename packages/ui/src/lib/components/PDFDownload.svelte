<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Props {
		url: string;
		filename?: string;
		languages?: string[];
		class?: string;
	}

	let {
		url,
		filename = "document.pdf",
		languages = ["en"],
		class: className,
	}: Props = $props();

	let loading = $state(false);
	let selectedLang = $state(languages[0] ?? "en");

	async function download() {
		loading = true;
		try {
			const separator = url.includes("?") ? "&" : "?";
			const fetchUrl =
				languages.length > 1 ? `${url}${separator}lang=${selectedLang}` : url;

			const response = await fetch(fetchUrl);
			if (!response.ok) throw new Error("Download failed");

			const blob = await response.blob();
			const blobUrl = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = blobUrl;
			a.download = filename;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(blobUrl);
		} catch (err) {
			console.error("PDF download failed:", err);
		} finally {
			loading = false;
		}
	}
</script>

<div class={cn("inline-flex items-center gap-2", className)}>
	{#if languages.length > 1}
		<div class="inline-flex rounded-md border border-[var(--netz-border)]">
			{#each languages as lang}
				<button
					class={cn(
						"px-2 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md",
						selectedLang === lang
							? "bg-[var(--netz-brand-primary)] text-white"
							: "bg-[var(--netz-surface)] text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]",
					)}
					onclick={() => (selectedLang = lang)}
				>
					{lang.toUpperCase()}
				</button>
			{/each}
		</div>
	{/if}
	<button
		class="inline-flex h-9 items-center gap-2 rounded-md bg-[var(--netz-brand-primary)] px-4 text-sm font-medium text-white transition-colors hover:bg-[var(--netz-brand-primary)]/90 disabled:opacity-50"
		onclick={download}
		disabled={loading}
	>
		{#if loading}
			<svg
				class="h-4 w-4 animate-spin"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
			>
				<circle
					class="opacity-25"
					cx="12"
					cy="12"
					r="10"
					stroke="currentColor"
					stroke-width="4"
				></circle>
				<path
					class="opacity-75"
					fill="currentColor"
					d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
				></path>
			</svg>
		{:else}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="16"
				height="16"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
			>
				<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
				<polyline points="7 10 12 15 17 10" />
				<line x1="12" y1="15" x2="12" y2="3" />
			</svg>
		{/if}
		Download PDF
	</button>
</div>
