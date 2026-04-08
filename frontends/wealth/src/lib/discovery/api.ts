/**
 * Discovery API client.
 *
 * All functions accept a `getToken` callback (typically obtained via
 * `getContext<() => Promise<string>>("netz:getToken")` in the calling
 * component) and build Clerk JWT headers. SSE uses `fetch()` +
 * `ReadableStream` — NEVER `EventSource`, since auth headers are required.
 */
const BASE = "/api/wealth/discovery";

export type GetToken = () => Promise<string>;

async function authHeaders(getToken: GetToken): Promise<HeadersInit> {
	const token = await getToken();
	return { Authorization: `Bearer ${token}` };
}

export async function fetchManagers(
	getToken: GetToken,
	body: object,
	signal: AbortSignal,
): Promise<{ rows: unknown[]; next_cursor?: string | null }> {
	const res = await fetch(`${BASE}/managers`, {
		method: "POST",
		headers: {
			...(await authHeaders(getToken)),
			"Content-Type": "application/json",
		},
		body: JSON.stringify(body),
		signal,
	});
	if (!res.ok) throw new Error(`managers fetch: ${res.status}`);
	return res.json();
}

export async function fetchFundsByManager(
	getToken: GetToken,
	managerId: string,
	body: object,
	signal: AbortSignal,
): Promise<{ rows: unknown[]; next_cursor?: string | null }> {
	const res = await fetch(
		`${BASE}/managers/${encodeURIComponent(managerId)}/funds`,
		{
			method: "POST",
			headers: {
				...(await authHeaders(getToken)),
				"Content-Type": "application/json",
			},
			body: JSON.stringify(body),
			signal,
		},
	);
	if (!res.ok) throw new Error(`funds fetch: ${res.status}`);
	return res.json();
}

export async function fetchFundFactSheet(
	getToken: GetToken,
	fundId: string,
	signal: AbortSignal,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/fact-sheet`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`factsheet fetch: ${res.status}`);
	return res.json();
}

export async function openDDReportStream(
	getToken: GetToken,
	fundId: string,
	signal: AbortSignal,
	onEvent: (evt: { event: string; data: unknown }) => void,
): Promise<void> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/dd-report/stream`,
		{
			headers: {
				...(await authHeaders(getToken)),
				Accept: "text/event-stream",
			},
			signal,
		},
	);
	if (!res.ok || !res.body) throw new Error(`dd stream: ${res.status}`);
	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buf = "";
	while (true) {
		const { done, value } = await reader.read();
		if (done) return;
		buf += decoder.decode(value, { stream: true });
		const frames = buf.split("\n\n");
		buf = frames.pop() ?? "";
		for (const frame of frames) {
			const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
			const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
			if (!dataLine) continue;
			try {
				onEvent({
					event: eventLine?.slice(7) ?? "message",
					data: JSON.parse(dataLine.slice(6)),
				});
			} catch {
				/* skip malformed frame */
			}
		}
	}
}
