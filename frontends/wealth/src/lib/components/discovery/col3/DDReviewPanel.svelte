<!--
  DDReviewPanel — col3 quick-read panel that streams the DD report for the
  selected fund via SSE (fetch + ReadableStream — NEVER EventSource, since we
  need Clerk JWT auth headers). Consumes `snapshot` (initial full list) and
  `chapter` (incremental updates) events.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { openDDReportStream } from "$wealth/discovery/api";

	interface Props {
		fundId: string;
	}
	let { fundId }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Chapter {
		chapter_tag: string;
		chapter_order: number;
		content_md: string;
		critic_status: string | null;
	}

	let chapters = $state<Chapter[]>([]);
	let status = $state<"idle" | "streaming" | "done" | "error">("idle");
	let error = $state<string | null>(null);

	$effect(() => {
		const id = fundId;
		if (!id) return;
		const ctrl = new AbortController();
		chapters = [];
		error = null;
		status = "streaming";
		(async () => {
			try {
				await openDDReportStream(getToken, id, ctrl.signal, (evt) => {
					if (evt.event === "snapshot") {
						chapters = (evt.data as { chapters: Chapter[] }).chapters;
					} else if (evt.event === "chapter") {
						const ch = evt.data as Chapter;
						const existing = chapters.findIndex(
							(c) => c.chapter_order === ch.chapter_order,
						);
						if (existing >= 0) {
							chapters = chapters.map((c, i) => (i === existing ? ch : c));
						} else {
							chapters = [...chapters, ch].sort(
								(a, b) => a.chapter_order - b.chapter_order,
							);
						}
					}
				});
				status = "done";
			} catch (e) {
				if ((e as Error).name === "AbortError") return;
				error = (e as Error).message;
				status = "error";
			}
		})();
		return () => ctrl.abort();
	});
</script>

<div class="dd-root">
	<header class="dd-header">
		<h2>DD Review</h2>
		<span class="status" data-state={status}>{status}</span>
	</header>
	{#if error}
		<div class="dd-error">Failed: {error}</div>
	{:else if chapters.length === 0 && status === "streaming"}
		<div class="dd-loading">Waiting for first chapter…</div>
	{:else}
		<div class="dd-chapters">
			{#each chapters as ch (ch.chapter_order)}
				<article class="dd-chapter">
					<h3>{ch.chapter_tag}</h3>
					<div class="dd-content">{ch.content_md}</div>
					{#if ch.critic_status}
						<span class="dd-critic">Critic: {ch.critic_status}</span>
					{/if}
				</article>
			{/each}
		</div>
	{/if}
</div>

<style>
	.dd-root {
		padding: 24px;
		font-family: "Urbanist", system-ui, sans-serif;
		height: 100%;
		overflow: auto;
	}
	.dd-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 16px;
	}
	.dd-header h2 {
		font-size: 18px;
		font-weight: 600;
		margin: 0;
	}
	.status {
		font-size: 11px;
		text-transform: uppercase;
		color: var(--ii-text-muted);
	}
	.status[data-state="streaming"] {
		color: var(--ii-brand-accent);
	}
	.status[data-state="done"] {
		color: var(--ii-success);
	}
	.status[data-state="error"] {
		color: var(--ii-danger);
	}
	.dd-chapter {
		padding: 16px 0;
		border-bottom: 1px solid var(--ii-border-subtle);
	}
	.dd-chapter h3 {
		font-size: 13px;
		font-weight: 600;
		margin: 0 0 8px;
	}
	.dd-content {
		font-size: 13px;
		line-height: 1.6;
		white-space: pre-wrap;
	}
	.dd-critic {
		font-size: 11px;
		color: var(--ii-text-muted);
		margin-top: 8px;
		display: block;
	}
	.dd-loading,
	.dd-error {
		padding: 16px 0;
		color: var(--ii-text-muted);
	}
	.dd-error {
		color: var(--ii-danger);
	}
</style>
