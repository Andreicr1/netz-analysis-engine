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
			throw new AuthError(parsed?.detail as string ?? "Authentication required");
		case 403:
			throw new ForbiddenError(parsed?.detail as string ?? "Access denied");
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

export class NetzApiClient {
	private baseUrl: string;
	private getToken: () => Promise<string> | string;

	constructor(baseUrl: string, getToken: () => Promise<string> | string) {
		this.baseUrl = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
		this.getToken = getToken;
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
		const res = await fetch(url, { headers: await this.headers() });
		return handleResponse<T>(res);
	}

	async post<T>(path: string, body?: unknown): Promise<T> {
		const res = await fetch(buildUrl(this.baseUrl, path), {
			method: "POST",
			headers: await this.headers(),
			body: body !== undefined ? JSON.stringify(body) : undefined,
		});
		return handleResponse<T>(res);
	}

	async patch<T>(path: string, body?: unknown): Promise<T> {
		const res = await fetch(buildUrl(this.baseUrl, path), {
			method: "PATCH",
			headers: await this.headers(),
			body: body !== undefined ? JSON.stringify(body) : undefined,
		});
		return handleResponse<T>(res);
	}

	async delete(path: string): Promise<void> {
		const res = await fetch(buildUrl(this.baseUrl, path), {
			method: "DELETE",
			headers: await this.headers(),
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
