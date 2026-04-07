<!--
  AI Agent Drawer — slide-in chat panel with SSE-streamed responses.
  Multi-turn conversation with tool call indicators and inline citations.
  Uses fetch() + ReadableStream (never EventSource — auth headers needed).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { X, Bot, SendHorizonal, FileText } from "lucide-svelte";
	import { Spinner } from "@investintell/ui/components/ui/spinner";
	import * as Sheet from "@investintell/ui/components/ui/sheet";

	interface Props {
		open: boolean;
		onclose: () => void;
		instrumentId?: string | null;
		secCrd?: string | null;
		esmaManagerId?: string | null;
	}

	let { open, onclose, instrumentId = null, secCrd = null, esmaManagerId = null }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface ChatMessage {
		role: "user" | "assistant";
		content: string;
		citations?: Citation[];
		toolCalls?: ToolCall[];
		isStreaming?: boolean;
	}

	interface Citation {
		chunk_id: string;
		excerpt?: string;
	}

	interface ToolCall {
		tool: string;
		status: "running" | "complete" | "error";
		detail: string;
	}

	let messages = $state<ChatMessage[]>([]);
	let inputText = $state("");
	let isLoading = $state(false);
	let abortController = $state<AbortController | null>(null);
	let chatContainer = $state<HTMLDivElement | null>(null);

	function scrollToBottom() {
		requestAnimationFrame(() => {
			if (chatContainer) {
				chatContainer.scrollTop = chatContainer.scrollHeight;
			}
		});
	}

	function resetChat() {
		messages = [];
		inputText = "";
		isLoading = false;
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
	}

	function updateAssistantMsg(idx: number, patch: Partial<Omit<ChatMessage, "role">>) {
		const existing = messages[idx];
		if (!existing) return;
		messages[idx] = { ...existing, ...patch };
		messages = messages; // trigger reactivity
		scrollToBottom();
	}

	async function sendMessage() {
		const text = inputText.trim();
		if (!text || isLoading) return;

		inputText = "";
		messages = [...messages, { role: "user", content: text }];

		// Add placeholder assistant message
		const assistantIdx = messages.length;
		messages = [...messages, { role: "assistant", content: "", toolCalls: [], citations: [], isStreaming: true }];
		isLoading = true;
		scrollToBottom();

		const controller = new AbortController();
		abortController = controller;

		try {
			const token = getToken ? await getToken() : "";
			const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

			// Build message history for multi-turn (exclude the streaming placeholder)
			const apiMessages = messages
				.filter((m) => !m.isStreaming)
				.map((m) => ({ role: m.role, content: m.content }));

			const response = await fetch(`${apiBase}/wealth/agent/chat`, {
				method: "POST",
				headers: {
					Authorization: `Bearer ${token}`,
					"Content-Type": "application/json",
					Accept: "text/event-stream",
				},
				body: JSON.stringify({
					messages: apiMessages,
					instrument_id: instrumentId,
					sec_crd: secCrd,
					esma_manager_id: esmaManagerId,
				}),
				signal: controller.signal,
			});

			if (!response.ok || !response.body) {
				updateAssistantMsg(assistantIdx, { content: "Failed to connect to AI Agent.", isStreaming: false });
				isLoading = false;
				return;
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";
			let lastEventType = "message";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					const trimmed = line.trim();
					if (trimmed === "" || trimmed.startsWith(":")) continue;

					if (trimmed.startsWith("event:")) {
						lastEventType = trimmed.slice(6).trim();
						continue;
					}

					if (!trimmed.startsWith("data:")) continue;

					const raw = trimmed.slice(5).trim();
					if (!raw) continue;

					let data: Record<string, unknown>;
					try {
						data = JSON.parse(raw);
					} catch {
						continue;
					}

					const msg = messages[assistantIdx]!;

					if (lastEventType === "tool_call") {
						const tc: ToolCall = {
							tool: String(data.tool ?? ""),
							status: String(data.status ?? "running") as ToolCall["status"],
							detail: String(data.detail ?? ""),
						};
						// Update existing tool or add new one
						const existing = (msg.toolCalls ?? []).findIndex((t) => t.tool === tc.tool);
						const tools = [...(msg.toolCalls ?? [])];
						if (existing >= 0) {
							tools[existing] = tc;
						} else {
							tools.push(tc);
						}
						updateAssistantMsg(assistantIdx, { toolCalls: tools });
					} else if (lastEventType === "chunk") {
						const newText = (msg.content || "") + String(data.text ?? "");
						updateAssistantMsg(assistantIdx, { content: newText });
					} else if (lastEventType === "citations") {
						const cites = (data.citations ?? []) as Citation[];
						updateAssistantMsg(assistantIdx, { citations: cites });
					} else if (lastEventType === "done") {
						updateAssistantMsg(assistantIdx, { isStreaming: false });
					} else if (lastEventType === "error") {
						updateAssistantMsg(assistantIdx, {
							content: String(data.message ?? "An error occurred."),
							isStreaming: false,
						});
					}

					// Reset event type after processing
					lastEventType = "message";
				}
			}

			// Ensure streaming flag is off
			if (messages[assistantIdx]?.isStreaming) {
				updateAssistantMsg(assistantIdx, { isStreaming: false });
			}
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === "AbortError") {
				updateAssistantMsg(assistantIdx, { content: messages[assistantIdx]?.content || "Cancelled.", isStreaming: false });
			} else {
				updateAssistantMsg(assistantIdx, { content: "An error occurred. Please try again.", isStreaming: false });
			}
		} finally {
			isLoading = false;
			abortController = null;
			scrollToBottom();
		}
	}

	function citationLabel(chunkId: string): string {
		if (chunkId.startsWith("dd_chapter")) return "DD Report";
		if (chunkId.startsWith("macro_review")) return "Macro Review";
		if (chunkId.startsWith("adv_brochure") || chunkId.startsWith("brochure")) return "ADV Brochure";
		if (chunkId.startsWith("fact_sheet")) return "Fact Sheet";
		if (chunkId.startsWith("prospectus")) return "Prospectus";
		if (chunkId.startsWith("flash_report")) return "Flash Report";
		if (chunkId.startsWith("spotlight")) return "Manager Spotlight";
		if (chunkId.startsWith("outlook")) return "Investment Outlook";
		return "Document";
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	function cancelStream() {
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
	}
</script>

<Sheet.Root {open} onOpenChange={(v) => { if (!v) onclose(); }}>
	<Sheet.Content side="right" class="w-[420px] max-w-full sm:max-w-[420px] flex flex-col p-0 gap-0" showCloseButton={false}>
		<!-- Header -->
		<header class="agent-header">
			<div class="agent-header-title">
				<Bot size={18} />
				<span>AI Assistant</span>
			</div>
			<div class="agent-header-actions">
				<button class="agent-icon-btn" type="button" title="New chat" onclick={resetChat}>
					<FileText size={15} />
				</button>
				<Sheet.Close>
					{#snippet child({ props })}
						<button class="agent-icon-btn" type="button" title="Close" {...props}>
							<X size={18} />
						</button>
					{/snippet}
				</Sheet.Close>
			</div>
		</header>

		<!-- Messages -->
		<div class="agent-messages" bind:this={chatContainer}>
			{#if messages.length === 0}
				<div class="agent-empty">
					<Bot size={32} class="agent-empty-icon" />
					<p class="agent-empty-title">Wealth AI Assistant</p>
					<p class="agent-empty-desc">
						Ask about funds, managers, DD reports, portfolios, or macro analysis.
					</p>
				</div>
			{/if}

			{#each messages as msg, i (i)}
				<div class="agent-msg agent-msg--{msg.role}">
					{#if msg.role === "assistant"}
						<!-- Tool call indicators -->
						{#if msg.toolCalls && msg.toolCalls.filter(tc => tc.status === "running").length > 0}
							<div class="agent-tools">
								{#each msg.toolCalls.filter(tc => tc.status === "running") as tc (tc.tool)}
									<div class="agent-tool running">
										<Spinner class="size-3" />
										<span>{tc.detail}</span>
									</div>
								{/each}
							</div>
						{/if}

						<!-- Answer text -->
						{#if msg.content}
							<div class="agent-msg-text">{msg.content}</div>
						{:else if msg.isStreaming}
							<div class="agent-msg-text agent-msg-text--loading">
								<Spinner class="size-3.5" />
								<span>Thinking…</span>
							</div>
						{/if}

						<!-- Citations -->
						{#if msg.citations && msg.citations.length > 0}
							{@const documentedCites = msg.citations.filter(c => c.excerpt && c.excerpt.trim().length > 0)}
							{#if documentedCites.length > 0}
								<div class="agent-citations">
									<span class="agent-citations-label">Sources</span>
									{#each documentedCites as cite (cite.chunk_id)}
										<div class="agent-citation" title={cite.excerpt}>
											<FileText size={11} />
											<span>{citationLabel(cite.chunk_id)}</span>
										</div>
									{/each}
								</div>
							{/if}
						{/if}
					{:else}
						<div class="agent-msg-text">{msg.content}</div>
					{/if}
				</div>
			{/each}
		</div>

		<!-- Input -->
		<div class="agent-input-area">
			{#if isLoading}
				<button class="agent-cancel-btn" type="button" onclick={cancelStream}>
					Stop generating
				</button>
			{/if}
			<div class="agent-input-row">
				<textarea
					class="agent-input"
					placeholder="Ask about funds, managers, DD reports…"
					bind:value={inputText}
					onkeydown={handleKeydown}
					rows={1}
					disabled={isLoading}
				></textarea>
				<button
					class="agent-send-btn"
					type="button"
					onclick={sendMessage}
					disabled={isLoading || !inputText.trim()}
					title="Send"
				>
					<SendHorizonal size={16} />
				</button>
			</div>
		</div>
	</Sheet.Content>
</Sheet.Root>

<style>
	/* Header */
	.agent-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--ii-border-subtle);
		flex-shrink: 0;
	}

	.agent-header-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 14px;
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.agent-header-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.agent-icon-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-muted);
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease;
	}

	.agent-icon-btn:hover {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
	}

	/* Messages area */
	.agent-messages {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.agent-empty {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--ii-text-muted);
		text-align: center;
		padding: 48px 24px;
	}

	.agent-empty :global(.agent-empty-icon) { opacity: 0.3; }
	.agent-empty-title { font-size: 15px; font-weight: 600; color: var(--ii-text-secondary); margin: 0; }
	.agent-empty-desc { font-size: 13px; margin: 0; line-height: 1.5; }

	/* Messages */
	.agent-msg { max-width: 100%; }

	.agent-msg--user {
		align-self: flex-end;
		max-width: 85%;
	}

	.agent-msg--user .agent-msg-text {
		background: var(--ii-brand-primary, #1447e6);
		color: #fff;
		border-radius: 12px 12px 4px 12px;
		padding: 10px 14px;
		font-size: 13px;
		line-height: 1.5;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.agent-msg--assistant .agent-msg-text {
		background: var(--ii-surface-alt, #f5f8fd);
		color: var(--ii-text-primary);
		border-radius: 12px 12px 12px 4px;
		padding: 10px 14px;
		font-size: 13px;
		line-height: 1.6;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.agent-msg-text--loading {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--ii-text-muted);
		font-style: italic;
	}

	/* Tool calls */
	.agent-tools {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 8px;
	}

	.agent-tool {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		color: var(--ii-text-muted);
		padding: 4px 8px;
		border-radius: 6px;
		background: color-mix(in srgb, var(--ii-brand-highlight, #3b82f6) 6%, transparent);
	}

	.agent-tool.running { color: var(--ii-brand-highlight, #3b82f6); }


	/* Citations */
	.agent-citations {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 8px;
		align-items: center;
	}

	.agent-citations-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--ii-text-muted);
		margin-right: 4px;
	}

	.agent-citation {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 4px;
		background: var(--ii-surface-alt);
		border: 1px solid var(--ii-border-subtle);
		font-size: 10px;
		color: var(--ii-text-secondary);
		cursor: default;
	}

	/* Input area */
	.agent-input-area {
		padding: 12px 16px;
		border-top: 1px solid var(--ii-border-subtle);
		flex-shrink: 0;
	}

	.agent-input-row {
		display: flex;
		align-items: flex-end;
		gap: 8px;
		background: var(--ii-bg, #f5f8fd);
		border: 1px solid var(--ii-border);
		border-radius: 10px;
		padding: 8px 12px;
		transition: border-color 120ms ease;
	}

	.agent-input-row:focus-within {
		border-color: var(--ii-brand-highlight, #3b82f6);
	}

	.agent-input {
		flex: 1;
		border: none;
		background: transparent;
		color: var(--ii-text-primary);
		font-size: 13px;
		font-family: var(--ii-font-sans);
		resize: none;
		outline: none;
		line-height: 1.5;
		max-height: 120px;
	}

	.agent-input::placeholder {
		color: var(--ii-text-muted);
	}

	.agent-send-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: 8px;
		background: var(--ii-brand-primary, #1447e6);
		color: #fff;
		cursor: pointer;
		flex-shrink: 0;
		transition: opacity 120ms ease;
	}

	.agent-send-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.agent-send-btn:not(:disabled):hover {
		opacity: 0.9;
	}

	.agent-cancel-btn {
		display: block;
		width: 100%;
		padding: 6px;
		margin-bottom: 8px;
		border: 1px solid var(--ii-border);
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: 12px;
		cursor: pointer;
		transition: background 120ms ease;
	}

	.agent-cancel-btn:hover {
		background: var(--ii-surface-alt);
	}
</style>
