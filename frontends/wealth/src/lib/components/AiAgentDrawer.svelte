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
	<Sheet.Content
		side="right"
		class="w-[480px] max-w-full sm:max-w-[480px] flex flex-col p-0 gap-0 !bg-[var(--ii-surface-panel)] !border-l !border-white/10 shadow-[-20px_0_60px_-20px_rgba(0,0,0,0.65)]"
		showCloseButton={false}
	>
		<!-- Header -->
		<header class="agent-header">
			<div class="agent-header-title">
				<div class="agent-logo">
					<Bot size={16} />
				</div>
				<div class="agent-header-copy">
					<span class="agent-title">InvestIntell Copilot</span>
					<span class="agent-subtitle">
						<span class="agent-live-dot"></span>
						Online · Wealth Desk
					</span>
				</div>
			</div>
			<div class="agent-header-actions">
				<button class="agent-icon-btn" type="button" title="New chat" onclick={resetChat} aria-label="New chat">
					<FileText size={15} />
				</button>
				<Sheet.Close>
					{#snippet child({ props })}
						<button class="agent-icon-btn" type="button" title="Close" aria-label="Close" {...props}>
							<X size={16} />
						</button>
					{/snippet}
				</Sheet.Close>
			</div>
		</header>

		<!-- Messages -->
		<div class="agent-messages" bind:this={chatContainer}>
			{#if messages.length === 0}
				<div class="agent-empty">
					<div class="agent-empty-halo">
						<Bot size={26} />
					</div>
					<p class="agent-empty-title">How can I help you today?</p>
					<p class="agent-empty-desc">
						Ask about funds, managers, DD reports, portfolios, or macro analysis.
					</p>
					<div class="agent-suggestions">
						{#each [
							"Top 5 US large-cap funds YTD",
							"What's driving the regime shift?",
							"Summarize latest DD for VWELX",
							"Show peer group for BlackRock managers",
						] as s}
							<button
								type="button"
								class="agent-suggestion"
								onclick={() => { inputText = s; }}
							>{s}</button>
						{/each}
					</div>
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
	/* Force bits-ui dialog overlay behind the drawer to be a real
	 * opaque scrim — the shadcn default bg-black/10 left the dashboard
	 * fully legible behind the agent, making the drawer look
	 * "transparent" when it was actually just flanked by live cards. */
	:global([data-dialog-overlay]),
	:global([data-sheet-overlay]) {
		background: rgba(5, 8, 15, 0.68) !important;
		backdrop-filter: blur(6px);
	}

	/* Header */
	.agent-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 18px;
		border-bottom: 1px solid var(--ii-border-subtle);
		flex-shrink: 0;
		background:
			linear-gradient(180deg, rgba(1, 119, 251, 0.08) 0%, transparent 100%),
			var(--ii-surface-panel);
	}

	.agent-header-title {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.agent-logo {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		background: linear-gradient(135deg, #0177fb 0%, #6366f1 100%);
		color: #fff;
		box-shadow:
			0 0 0 1px var(--ii-border-subtle),
			0 4px 14px rgba(1, 119, 251, 0.35);
	}

	.agent-header-copy {
		display: flex;
		flex-direction: column;
		line-height: 1.2;
	}

	.agent-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--ii-text-primary);
		letter-spacing: 0.01em;
	}

	.agent-subtitle {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 10px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--ii-text-muted);
		margin-top: 2px;
	}

	.agent-live-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: #11ec79;
		box-shadow: 0 0 6px rgba(17, 236, 121, 0.75);
		animation: agent-pulse 2s ease-in-out infinite;
	}

	@keyframes agent-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.45; }
	}

	.agent-header-actions {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.agent-icon-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 8px;
		background: var(--ii-surface-elevated);
		color: var(--ii-text-muted);
		cursor: pointer;
		transition: background 140ms ease, color 140ms ease, border-color 140ms ease;
	}

	.agent-icon-btn:hover {
		background: var(--ii-surface-raised);
		color: var(--ii-text-primary);
		border-color: var(--ii-border);
	}

	/* Messages area */
	.agent-messages {
		flex: 1;
		overflow-y: auto;
		padding: 20px 18px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		background: var(--ii-surface-panel);
	}

	.agent-messages::-webkit-scrollbar {
		width: 8px;
	}
	.agent-messages::-webkit-scrollbar-track {
		background: transparent;
	}
	.agent-messages::-webkit-scrollbar-thumb {
		background: var(--ii-border-subtle);
		border-radius: 4px;
	}
	.agent-messages::-webkit-scrollbar-thumb:hover {
		background: var(--ii-border);
	}

	/* Empty state */
	.agent-empty {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		text-align: center;
		padding: 40px 24px;
	}

	.agent-empty-halo {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 56px;
		height: 56px;
		border-radius: 50%;
		background: radial-gradient(circle at center, rgba(1, 119, 251, 0.28) 0%, transparent 70%);
		color: #0177fb;
		border: 1px solid rgba(1, 119, 251, 0.3);
		box-shadow: 0 0 24px rgba(1, 119, 251, 0.22);
	}

	.agent-empty-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--ii-text-primary);
		margin: 6px 0 0 0;
	}

	.agent-empty-desc {
		font-size: 12px;
		margin: 0;
		line-height: 1.55;
		color: var(--ii-text-muted);
		max-width: 280px;
	}

	.agent-suggestions {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-top: 14px;
		width: 100%;
		max-width: 320px;
	}

	.agent-suggestion {
		text-align: left;
		font-size: 12px;
		color: var(--ii-text-secondary);
		padding: 9px 12px;
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border-subtle);
		border-radius: 10px;
		cursor: pointer;
		transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
	}

	.agent-suggestion:hover {
		background: var(--ii-surface-raised);
		border-color: rgba(1, 119, 251, 0.4);
		transform: translateX(2px);
	}

	/* Messages */
	.agent-msg { max-width: 100%; }

	.agent-msg--user {
		align-self: flex-end;
		max-width: 85%;
	}

	.agent-msg--user .agent-msg-text {
		background: linear-gradient(135deg, #0177fb 0%, #2563eb 100%);
		color: var(--ii-text-primary);
		border-radius: 14px 14px 4px 14px;
		padding: 10px 14px;
		font-size: 13px;
		line-height: 1.5;
		white-space: pre-wrap;
		word-break: break-word;
		box-shadow: 0 4px 14px rgba(1, 119, 251, 0.22);
	}

	.agent-msg--assistant .agent-msg-text {
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		border: 1px solid var(--ii-border-subtle);
		border-radius: 14px 14px 14px 4px;
		padding: 11px 14px;
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
		padding: 5px 10px;
		border-radius: 8px;
		background: rgba(1, 119, 251, 0.1);
		border: 1px solid rgba(1, 119, 251, 0.24);
	}

	.agent-tool.running { color: #6fa8ff; }

	/* Citations */
	.agent-citations {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 10px;
		align-items: center;
	}

	.agent-citations-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--ii-text-muted);
		margin-right: 4px;
	}

	.agent-citation {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 9px;
		border-radius: 6px;
		background: rgba(1, 119, 251, 0.12);
		border: 1px solid rgba(1, 119, 251, 0.28);
		font-size: 10px;
		color: var(--ii-text-muted);
		cursor: default;
	}

	/* Input area */
	.agent-input-area {
		padding: 14px 18px 16px;
		border-top: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-panel);
		flex-shrink: 0;
	}

	.agent-input-row {
		display: flex;
		align-items: flex-end;
		gap: 8px;
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border-subtle);
		border-radius: 12px;
		padding: 10px 12px;
		transition: border-color 140ms ease, box-shadow 140ms ease;
	}

	.agent-input-row:focus-within {
		border-color: rgba(1, 119, 251, 0.5);
		box-shadow: 0 0 0 3px rgba(1, 119, 251, 0.12);
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
		width: 34px;
		height: 34px;
		border: none;
		border-radius: 10px;
		background: linear-gradient(135deg, #0177fb 0%, #2563eb 100%);
		color: var(--ii-text-primary);
		cursor: pointer;
		flex-shrink: 0;
		transition: transform 140ms ease, box-shadow 140ms ease, opacity 140ms ease;
		box-shadow: 0 4px 14px rgba(1, 119, 251, 0.28);
	}

	.agent-send-btn:disabled {
		opacity: 0.35;
		cursor: not-allowed;
		box-shadow: none;
	}

	.agent-send-btn:not(:disabled):hover {
		transform: translateY(-1px);
		box-shadow: 0 6px 18px rgba(1, 119, 251, 0.38);
	}

	.agent-cancel-btn {
		display: block;
		width: 100%;
		padding: 8px;
		margin-bottom: 10px;
		border: 1px solid rgba(252, 26, 26, 0.28);
		border-radius: 8px;
		background: rgba(252, 26, 26, 0.08);
		color: #fc1a1a;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: background 140ms ease;
	}

	.agent-cancel-btn:hover {
		background: rgba(252, 26, 26, 0.16);
	}
</style>
