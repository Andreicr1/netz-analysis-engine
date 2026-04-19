/**
 * In-memory stale-while-revalidate cache for API responses.
 * No localStorage (per architectural rule). Cache lives only for the SPA session.
 *
 * Usage:
 *   import { cachedGet, invalidateCache } from "$wealth/api/cache";
 *   const data = await cachedGet(api, "/universe", {}, 300_000); // 5 min TTL
 */

interface CacheEntry {
	data: unknown;
	ts: number;
}

const cache = new Map<string, CacheEntry>();

/** Default TTL: 60 seconds */
const DEFAULT_TTL = 60_000;

/** Endpoint-specific TTLs (stable data gets longer TTL). */
const ENDPOINT_TTLS: Record<string, number> = {
	"/universe": 300_000,              // 5 min — changes only on import/approval
	"/blended-benchmarks/blocks": 300_000, // 5 min — structural, rarely changes
	"/model-portfolios": 120_000,       // 2 min — changes on create/update
	"/portfolios": 60_000,              // 1 min
};

function buildKey(url: string, params?: Record<string, string>): string {
	const qs = params ? JSON.stringify(params) : "";
	return `${url}${qs}`;
}

function ttlFor(url: string, explicitTtl?: number): number {
	if (explicitTtl !== undefined) return explicitTtl;
	// Match the longest prefix in ENDPOINT_TTLS
	for (const [prefix, ttl] of Object.entries(ENDPOINT_TTLS)) {
		if (url === prefix || url.startsWith(prefix + "/") || url.startsWith(prefix + "?")) {
			return ttl;
		}
	}
	return DEFAULT_TTL;
}

/**
 * Fetch with in-memory cache. Returns cached data if within TTL.
 * Falls through to live fetch on miss or expiry.
 */
export async function cachedGet<T>(
	api: { get: <R>(url: string, params?: Record<string, string>) => Promise<R> },
	url: string,
	params?: Record<string, string>,
	ttl?: number,
): Promise<T> {
	const key = buildKey(url, params);
	const entry = cache.get(key);
	const effectiveTtl = ttlFor(url, ttl);

	if (entry && Date.now() - entry.ts < effectiveTtl) {
		return entry.data as T;
	}

	const data = await api.get<T>(url, params);
	cache.set(key, { data, ts: Date.now() });
	return data;
}

/**
 * Invalidate cache entries.
 * - No args: clear everything.
 * - With prefix: clear entries whose URL starts with the prefix.
 */
export function invalidateCache(urlPrefix?: string): void {
	if (!urlPrefix) {
		cache.clear();
		return;
	}
	for (const key of cache.keys()) {
		if (key.startsWith(urlPrefix)) {
			cache.delete(key);
		}
	}
}
