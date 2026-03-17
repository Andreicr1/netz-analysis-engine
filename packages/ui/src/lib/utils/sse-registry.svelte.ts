/**
 * Global SSE connection counter.
 *
 * HTTP/1.1 has a 6-connection-per-origin limit. Reserve 2 for API calls,
 * allowing max 4 SSE connections per tab.
 */

const MAX_SSE_CONNECTIONS = 4;

let activeConnections = $state(0);

export function canOpenSSE(): boolean {
	return activeConnections < MAX_SSE_CONNECTIONS;
}

export function registerSSE(): boolean {
	if (activeConnections >= MAX_SSE_CONNECTIONS) return false;
	activeConnections++;
	return true;
}

export function unregisterSSE(): void {
	activeConnections = Math.max(0, activeConnections - 1);
}

export function getActiveSSECount(): number {
	return activeConnections;
}
