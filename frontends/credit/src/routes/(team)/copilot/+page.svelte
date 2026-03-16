<!--
  Fund Copilot — RAG-powered chat interface with SSE streaming.
-->
<script lang="ts">
	import { Card, Button, Input } from "@netz/ui";
	import { createSSEStream } from "@netz/ui/utils";
	import CopilotChat from "$lib/components/CopilotChat.svelte";

	let query = $state("");
	let messages = $state<Array<{ role: "user" | "assistant"; content: string; citations?: unknown[] }>>([]);
	let streaming = $state(false);

	async function submitQuery() {
		if (!query.trim() || streaming) return;

		const userMessage = query.trim();
		query = "";
		messages = [...messages, { role: "user", content: userMessage }];
		streaming = true;

		// Add placeholder for assistant response
		messages = [...messages, { role: "assistant", content: "", citations: [] }];

		const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

		try {
			// Use the /ai/answer endpoint for full RAG + LLM
			const res = await fetch(`${API_BASE}/api/v1/ai/answer`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					"Authorization": "Bearer dev-token",
				},
				body: JSON.stringify({ question: userMessage }),
			});

			if (!res.ok) throw new Error(`API error: ${res.status}`);

			const data = await res.json();
			// Update last assistant message
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

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault();
			submitQuery();
		}
	}
</script>

<div class="flex h-full flex-col p-6">
	<h2 class="mb-4 text-xl font-semibold text-[var(--netz-text-primary)]">Fund Copilot</h2>

	<CopilotChat {messages} {streaming} />

	<!-- Input area -->
	<div class="mt-4 flex gap-2">
		<input
			type="text"
			bind:value={query}
			placeholder="Ask about the fund portfolio, deals, documents..."
			class="flex-1 rounded-md border border-[var(--netz-border)] bg-white px-4 py-2.5 text-sm outline-none focus:border-[var(--netz-primary)] focus:ring-1 focus:ring-[var(--netz-primary)]"
			onkeydown={handleKeydown}
			disabled={streaming}
		/>
		<Button onclick={submitQuery} disabled={!query.trim() || streaming}>
			{streaming ? "Thinking..." : "Ask"}
		</Button>
	</div>
</div>
