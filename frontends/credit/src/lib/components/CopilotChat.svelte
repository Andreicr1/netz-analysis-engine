<!--
  @component CopilotChat
  Renders chat message history with citations.
-->
<script lang="ts">
	import { Card, EmptyState } from "@netz/ui";
	import CopilotCitation from "./CopilotCitation.svelte";

	interface Message {
		role: "user" | "assistant";
		content: string;
		citations?: unknown[];
	}

	let { messages = [], streaming = false }: { messages: Message[]; streaming: boolean } = $props();
</script>

<div class="flex-1 space-y-4 overflow-y-auto">
	{#if messages.length === 0}
		<EmptyState
			title="Fund Copilot"
			description="Ask questions about the fund portfolio, deals, documents, and market conditions. Answers are sourced from your indexed documents."
		/>
	{:else}
		{#each messages as message, i (i)}
			<div class="flex {message.role === 'user' ? 'justify-end' : 'justify-start'}">
				<div
					class="max-w-[80%] rounded-lg px-4 py-3 text-sm {message.role === 'user'
						? 'bg-(--netz-brand-primary) text-white'
						: 'bg-(--netz-surface) border border-(--netz-border) text-(--netz-text-primary)'}"
				>
					{#if message.content}
						<p class="whitespace-pre-wrap">{message.content}</p>
					{:else if streaming && i === messages.length - 1}
						<span class="inline-block h-4 w-1 animate-pulse bg-(--netz-brand-primary)"></span>
					{/if}

					{#if message.citations && (message.citations as unknown[]).length > 0}
						<div class="mt-2 border-t border-(--netz-border) pt-2">
							<p class="mb-1 text-xs font-medium text-(--netz-text-muted)">Sources:</p>
							{#each message.citations as citation, ci (ci)}
								<CopilotCitation {citation} />
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/each}
	{/if}
</div>
