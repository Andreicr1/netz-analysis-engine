// PR-A5 Section A.3 — shared SSE parser.
//
// Extracted verbatim from portfolio-workspace.runConstructJob (the canonical
// fetch()+ReadableStream implementation used since DL15 — EventSource cannot
// carry Clerk JWT on Authorization header, so fetch is mandatory).
//
// Contract:
//   parseSseStream(res, onEvent, signal)
//     - Streams ``res.body`` until the server closes the connection OR
//       ``signal`` is aborted. Callers drive early termination by calling
//       ``controller.abort()`` from inside ``onEvent`` when a terminal
//       payload arrives — this keeps the legacy early-exit semantics
//       without forcing the parser to know about domain terminals.
//     - Parses ``data:`` lines into JSON objects; malformed payloads are
//       silently skipped (matches legacy behaviour — the server never
//       emits anything but JSON on this channel).
//     - Always cancels the reader on exit so we do not leak pending reads.

export async function parseSseStream(
	res: Response,
	onEvent: (event: unknown) => void,
	signal: AbortSignal,
): Promise<void> {
	if (!res.ok || !res.body) {
		throw new Error(`SSE stream failed: HTTP ${res.status}`);
	}

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	let currentData = "";

	try {
		while (true) {
			if (signal.aborted) break;

			let chunk: ReadableStreamReadResult<Uint8Array>;
			try {
				chunk = await reader.read();
			} catch (err) {
				// AbortError is the legitimate terminal path when the caller
				// calls controller.abort() from onEvent. Propagate anything else.
				if ((err as { name?: string } | null)?.name === "AbortError") break;
				throw err;
			}

			if (chunk.done) break;

			buffer += decoder.decode(chunk.value, { stream: true });
			buffer = buffer.replace(/\r\n/g, "\n");
			const lines = buffer.split("\n");
			buffer = lines.pop() ?? "";

			for (const line of lines) {
				if (line.startsWith("data:")) {
					currentData += (currentData ? "\n" : "") + line.slice(5).replace(/^ /, "");
				} else if (line === "") {
					if (currentData) {
						let parsed: unknown = null;
						try {
							parsed = JSON.parse(currentData);
						} catch {
							parsed = null;
						}
						if (parsed !== null) {
							onEvent(parsed);
						}
						currentData = "";
					}
				}
			}
		}
	} finally {
		reader.cancel().catch(() => {
			/* ignore abort noise */
		});
	}
}
