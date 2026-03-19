<!--
  Fund Copilot — RAG-powered chat interface with SSE streaming.
  Enhanced: History sidebar, Activity log, Document retrieval.
-->
<script lang="ts">
	import { Card, Button, PageTabs, EmptyState, DataTable, formatPercent, formatDateTime, PageHeader } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import CopilotChat from "$lib/components/CopilotChat.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Chat State ──
	let query = $state("");
	let messages = $state<Array<{ role: "user" | "assistant"; content: string; citations?: unknown[] }>>([]);
	let streaming = $state(false);

	// ── Sidebar State ──
	let sidebarTab = $state<"chat" | "history" | "activity" | "retrieve">("chat");
	let history = $state<Array<{ question: string; answer: string; created_at: string }>>([]);
	let activity = $state<Array<{ action: string; detail: string; created_at: string }>>([]);
	let historyLoaded = $state(false);
	let activityLoaded = $state(false);
	let loadingHistory = $state(false);
	let loadingActivity = $state(false);

	let actionError = $state<string | null>(null);

	// ── Retrieve State ──
	let retrieveQuery = $state("");
	let retrieveResults = $state<Array<{ title: string; score: number; snippet: string }>>([]);
	let retrieving = $state(false);

	async function submitQuery() {
		if (!query.trim() || streaming) return;

		const userMessage = query.trim();
		query = "";
		messages = [...messages, { role: "user", content: userMessage }];
		streaming = true;
		sidebarTab = "chat";

		messages = [...messages, { role: "assistant", content: "", citations: [] }];

		try {
			const api = createClientApiClient(getToken);
			const data = await api.post<{ answer?: string; citations?: unknown[] }>("/ai/answer", { question: userMessage });

			messages = messages.map((m, i) =>
				i === messages.length - 1
					? { ...m, content: data.answer ?? "No answer generated.", citations: data.citations ?? [] }
					: m,
			);
		} catch {
			messages = messages.map((m, i) =>
				i === messages.length - 1
					? { ...m, content: "Failed to get a response. Please try again." }
					: m,
			);
		} finally {
			streaming = false;
		}
	}

	async function loadHistory() {
		if (historyLoaded) return;
		loadingHistory = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<{ items: typeof history }>("/ai/history");
			history = res.items ?? [];
			historyLoaded = true;
		} catch (e) {
			history = [];
			actionError = e instanceof Error ? e.message : "Failed to load history";
		} finally {
			loadingHistory = false;
		}
	}

	async function loadActivity() {
		if (activityLoaded) return;
		loadingActivity = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<{ items: typeof activity }>("/ai/activity");
			activity = res.items ?? [];
			activityLoaded = true;
		} catch (e) {
			activity = [];
			actionError = e instanceof Error ? e.message : "Failed to load activity";
		} finally {
			loadingActivity = false;
		}
	}

	async function searchDocuments() {
		if (!retrieveQuery.trim()) return;
		retrieving = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ results: typeof retrieveResults }>("/ai/retrieve", {
				query: retrieveQuery.trim(),
				top_k: 10,
			});
			retrieveResults = res.results ?? [];
		} catch (e) {
			retrieveResults = [];
			actionError = e instanceof Error ? e.message : "Search failed";
		} finally {
			retrieving = false;
		}
	}

	function switchTab(tab: typeof sidebarTab) {
		sidebarTab = tab;
		if (tab === "history") loadHistory();
		if (tab === "activity") loadActivity();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault();
			submitQuery();
		}
	}

	function replayFromHistory(question: string) {
		query = question;
		sidebarTab = "chat";
		submitQuery();
	}
</script>

<div class="flex h-full flex-col px-6">
	<PageHeader title="Fund Copilot" />

	{#if actionError}
		<div class="mb-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Tab bar -->
	<PageTabs
		tabs={[
			{ id: "chat", label: "Chat" },
			{ id: "history", label: "History" },
			{ id: "activity", label: "Activity" },
			{ id: "retrieve", label: "Document Search" },
		]}
		active={sidebarTab}
		onChange={(tab) => switchTab(tab as typeof sidebarTab)}
	/>

	<div class="mt-4 flex-1 overflow-hidden">
		{#if sidebarTab === "chat"}
			<div class="flex h-full flex-col">
				<div class="flex-1 overflow-y-auto">
					<CopilotChat {messages} {streaming} />
				</div>

				<div class="mt-4 flex gap-2">
					<input
						type="text"
						bind:value={query}
						placeholder="Ask about the fund portfolio, deals, documents..."
						class="flex-1 rounded-md border border-(--netz-border) bg-(--netz-surface) px-4 py-2.5 text-sm outline-none focus:border-(--netz-brand-primary) focus:ring-1 focus:ring-(--netz-brand-primary)"
						onkeydown={handleKeydown}
						disabled={streaming}
					/>
					<Button onclick={submitQuery} disabled={!query.trim() || streaming}>
						{streaming ? "Thinking..." : "Ask"}
					</Button>
				</div>
			</div>

		{:else if sidebarTab === "history"}
			{#if loadingHistory}
				<p class="text-sm text-(--netz-text-muted)">Loading history...</p>
			{:else if history.length === 0}
				<EmptyState title="No History" description="Your past queries will appear here." />
			{:else}
				<div class="space-y-3 overflow-y-auto">
					{#each history as item}
						<Card class="cursor-pointer p-4 hover:bg-(--netz-surface-alt)" onclick={() => replayFromHistory(item.question)}>
							<p class="text-sm font-medium text-(--netz-text-primary)">{item.question}</p>
							<p class="mt-1 line-clamp-2 text-xs text-(--netz-text-muted)">{item.answer}</p>
							<p class="mt-1 text-xs text-(--netz-text-muted)">{formatDateTime(item.created_at)}</p>
						</Card>
					{/each}
				</div>
			{/if}

		{:else if sidebarTab === "activity"}
			{#if loadingActivity}
				<p class="text-sm text-(--netz-text-muted)">Loading activity...</p>
			{:else if activity.length === 0}
				<EmptyState title="No Activity" description="AI operation logs will appear here." />
			{:else}
				<div class="space-y-2 overflow-y-auto">
					{#each activity as item}
						<Card class="p-3">
							<p class="text-xs font-medium text-(--netz-text-primary)">{item.action}</p>
							<p class="text-xs text-(--netz-text-muted)">{item.detail}</p>
							<p class="mt-1 text-xs text-(--netz-text-muted)">{formatDateTime(item.created_at)}</p>
						</Card>
					{/each}
				</div>
			{/if}

		{:else if sidebarTab === "retrieve"}
			<div class="space-y-4">
				<div class="flex gap-2">
					<input
						type="text"
						bind:value={retrieveQuery}
						placeholder="Search documents by semantic query..."
						class="flex-1 rounded-md border border-(--netz-border) bg-(--netz-surface) px-4 py-2.5 text-sm outline-none focus:border-(--netz-brand-primary)"
						onkeydown={(e) => { if (e.key === "Enter") searchDocuments(); }}
					/>
					<ActionButton onclick={searchDocuments} loading={retrieving} loadingText="Searching...">
						Search
					</ActionButton>
				</div>

				{#if retrieveResults.length > 0}
					<div class="space-y-2 overflow-y-auto">
						{#each retrieveResults as doc}
							<Card class="p-3">
								<div class="flex items-start justify-between">
									<p class="text-sm font-medium text-(--netz-text-primary)">{doc.title}</p>
									<span class="ml-2 shrink-0 rounded-full bg-(--netz-brand-primary)/10 px-2 py-0.5 text-xs text-(--netz-brand-primary)">
										{formatPercent(doc.score)}
									</span>
								</div>
								<p class="mt-1 line-clamp-3 text-xs text-(--netz-text-muted)">{doc.snippet}</p>
							</Card>
						{/each}
					</div>
				{:else if retrieveQuery && !retrieving}
					<EmptyState title="No Results" description="No documents matched your query." />
				{/if}
			</div>
		{/if}
	</div>
</div>
