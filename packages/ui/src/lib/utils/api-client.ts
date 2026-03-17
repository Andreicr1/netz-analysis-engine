/** Netz API client with auth injection and typed error handling. */

export class AuthError extends Error {
	readonly status = 401;
	constructor(message = "Authentication required") {
		super(message);
		this.name = "AuthError";
	}
}

export class ForbiddenError extends Error {
	readonly status = 403;
	constructor(message = "Access denied") {
		super(message);
		this.name = "ForbiddenError";
	}
}

export class ValidationError extends Error {
	readonly status = 422;
	readonly details: unknown;
	constructor(message: string, details: unknown) {
		super(message);
		this.name = "ValidationError";
		this.details = details;
	}
}

export class ServerError extends Error {
	readonly status: number;
	constructor(message: string, status: number) {
		super(message);
		this.name = "ServerError";
		this.status = status;
	}
}

export class ConflictError extends Error {
	readonly status = 409;
	readonly currentVersion: number | undefined;
	constructor(message: string, currentVersion?: number) {
		super(message);
		this.name = "ConflictError";
		this.currentVersion = currentVersion;
	}
}

/**
 * Single-flight 401 redirect gate.
 * Prevents multiple concurrent goto('/auth/sign-in') when several
 * parallel requests all return 401 at the same time.
 */
let redirecting = false;

/** Reset redirect gate — called by consuming frontend after navigation completes. */
export function resetRedirectGate(): void {
	redirecting = false;
}

/** Check if a 401 redirect is already in progress. */
export function isRedirecting(): boolean {
	return redirecting;
}

/**
 * Optional 409 conflict callback. Set by the consuming frontend to
 * trigger toast + invalidateAll() on optimistic lock conflicts.
 * Avoids importing \$app/navigation directly from library code.
 */
let onConflict: ((message: string) => void) | null = null;

/** Register a handler for 409 conflict responses (call once in root layout). */
export function setConflictHandler(handler: (message: string) => void): void {
	onConflict = handler;
}

/**
 * Optional 401 redirect callback. Set by the consuming frontend to
 * trigger goto('/auth/sign-in'). Avoids importing \$app/navigation
 * directly from library code.
 */
let onAuthRedirect: (() => Promise<void> | void) | null = null;

/** Register a handler for 401 auth redirects (call once in root layout). */
export function setAuthRedirectHandler(handler: () => Promise<void> | void): void {
	onAuthRedirect = handler;
}

async function handleResponse<T>(res: Response): Promise<T> {
	if (res.ok) {
		if (res.status === 204) return undefined as T;
		return res.json() as Promise<T>;
	}

	const body = await res.text().catch(() => "");
	let parsed: Record<string, unknown> | null = null;
	try {
		parsed = JSON.parse(body);
	} catch {
		// not JSON
	}

	switch (res.status) {
		case 401:
			if (!redirecting) {
				redirecting = true;
				if (onAuthRedirect) {
					await onAuthRedirect();
				}
				// Reset after a tick to allow the redirect to complete
				setTimeout(() => { redirecting = false; }, 2000);
			}
			throw new AuthError(parsed?.detail as string ?? "Authentication required");
		case 403:
			throw new ForbiddenError(parsed?.detail as string ?? "Access denied");
		case 409: {
			const message = parsed?.detail as string ?? "Resource was modified by another user";
			onConflict?.(message);
			throw new ConflictError(message, parsed?.current_version as number | undefined);
		}
		case 422:
			throw new ValidationError(
				parsed?.detail as string ?? "Validation failed",
				parsed?.errors ?? parsed,
			);
		default:
			if (res.status >= 500) {
				throw new ServerError(parsed?.detail as string ?? `Server error (${res.status})`, res.status);
			}
			throw new Error(parsed?.detail as string ?? `Request failed (${res.status})`);
	}
}

function buildUrl(base: string, path: string, params?: Record<string, string | number | boolean | undefined>): string {
	const url = new URL(path, base);
	if (params) {
		for (const [k, v] of Object.entries(params)) {
			if (v !== undefined) url.searchParams.set(k, String(v));
		}
	}
	return url.toString();
}

/** Default request timeout (ms). */
const DEFAULT_TIMEOUT_MS = 15_000;

export class NetzApiClient {
	private baseUrl: string;
	private getToken: () => Promise<string> | string;
	private timeoutMs: number;

	constructor(baseUrl: string, getToken: () => Promise<string> | string, timeoutMs = DEFAULT_TIMEOUT_MS) {
		this.baseUrl = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
		this.getToken = getToken;
		this.timeoutMs = timeoutMs;
	}

	private async headers(): Promise<Record<string, string>> {
		const token = await this.getToken();
		return {
			Authorization: `Bearer ${token}`,
			"Content-Type": "application/json",
		};
	}

	async get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
		const url = buildUrl(this.baseUrl, path, params);
		const headers = await this.headers();
		// GET is idempotent — retry once on timeout/network error
		try {
			const res = await fetch(url, { headers, signal: AbortSignal.timeout(this.timeoutMs) });
			return handleResponse<T>(res);
		} catch (err) {
			if (err instanceof DOMException && err.name === "TimeoutError") {
				// Retry once
				const res = await fetch(url, { headers, signal: AbortSignal.timeout(this.timeoutMs) });
				return handleResponse<T>(res);
			}
			throw err;
		}
	}

	async post<T>(path: string, body?: unknown): Promise<T> {
		const res = await fetch(buildUrl(this.baseUrl, path), {
			method: "POST",
			headers: await this.headers(),
			body: body !== undefined ? JSON.stringify(body) : undefined,
			signal: AbortSignal.timeout(this.timeoutMs),
		});
		return handleResponse<T>(res);
	}

	async patch<T>(path: string, body?: unknown): Promise<T> {
		const res = await fetch(buildUrl(this.baseUrl, path), {
			method: "PATCH",
			headers: await this.headers(),
			body: body !== undefined ? JSON.stringify(body) : undefined,
			signal: AbortSignal.timeout(this.timeoutMs),
		});
		return handleResponse<T>(res);
	}

	async delete(path: string): Promise<void> {
		const res = await fetch(buildUrl(this.baseUrl, path), {
			method: "DELETE",
			headers: await this.headers(),
			signal: AbortSignal.timeout(this.timeoutMs),
		});
		await handleResponse<void>(res);
	}
}

/** Factory for +page.server.ts (token already resolved). */
export function createServerApiClient(baseUrl: string, token: string): NetzApiClient {
	return new NetzApiClient(baseUrl, () => token);
}

/** Factory for client-side (token from Clerk). */
export function createClientApiClient(baseUrl: string, getToken: () => Promise<string>): NetzApiClient {
	return new NetzApiClient(baseUrl, getToken);
}
