import { describe, it, expect, vi, beforeEach } from "vitest";
import {
	NetzApiClient,
	AuthError,
	ForbiddenError,
	ConflictError,
	ServerError,
	setAuthRedirectHandler,
	setConflictHandler,
	resetRedirectGate,
	isRedirecting,
	createServerApiClient,
	createClientApiClient,
} from "../api-client.js";

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(status: number, body: unknown = {}): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

beforeEach(() => {
	vi.clearAllMocks();
	resetRedirectGate();
	setAuthRedirectHandler(null as unknown as () => void);
	setConflictHandler(null as unknown as (msg: string) => void);
});

describe("NetzApiClient basics", () => {
	it("makes GET request with auth header", async () => {
		mockFetch.mockResolvedValueOnce(jsonResponse(200, { id: 1 }));
		const client = createServerApiClient("http://api.test", "tok123");
		const result = await client.get<{ id: number }>("/items");
		expect(result).toEqual({ id: 1 });
		expect(mockFetch).toHaveBeenCalledOnce();
		const [url, opts] = mockFetch.mock.calls[0]!;
		expect(url).toContain("/items");
		expect(opts.headers.Authorization).toBe("Bearer tok123");
	});

	it("makes POST request with body", async () => {
		mockFetch.mockResolvedValueOnce(jsonResponse(201, { id: 2 }));
		const client = createServerApiClient("http://api.test", "tok");
		await client.post("/items", { name: "test" });
		const [, opts] = mockFetch.mock.calls[0]!;
		expect(opts.method).toBe("POST");
		expect(opts.body).toBe(JSON.stringify({ name: "test" }));
	});

	it("handles 204 No Content", async () => {
		mockFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
		const client = createServerApiClient("http://api.test", "tok");
		const result = await client.delete("/items/1");
		expect(result).toBeUndefined();
	});

	it("throws ForbiddenError on 403", async () => {
		mockFetch.mockResolvedValueOnce(jsonResponse(403, { detail: "Nope" }));
		const client = createServerApiClient("http://api.test", "tok");
		await expect(client.get("/secret")).rejects.toThrow(ForbiddenError);
	});

	it("throws ServerError on 500", async () => {
		mockFetch.mockResolvedValueOnce(jsonResponse(500, { detail: "Boom" }));
		const client = createServerApiClient("http://api.test", "tok");
		await expect(client.get("/broken")).rejects.toThrow(ServerError);
	});
});

describe("single-flight 401 redirect", () => {
	it("fires redirect handler only once for 5 concurrent 401s", async () => {
		const redirectHandler = vi.fn();
		setAuthRedirectHandler(redirectHandler);

		mockFetch.mockImplementation(() =>
			Promise.resolve(jsonResponse(401, { detail: "Expired" })),
		);

		const client = createServerApiClient("http://api.test", "tok");

		// Fire 5 concurrent requests that all return 401
		const results = await Promise.allSettled([
			client.get("/a"),
			client.get("/b"),
			client.get("/c"),
			client.get("/d"),
			client.get("/e"),
		]);

		// All should throw AuthError
		for (const r of results) {
			expect(r.status).toBe("rejected");
			expect((r as PromiseRejectedResult).reason).toBeInstanceOf(AuthError);
		}

		// Redirect handler called exactly once
		expect(redirectHandler).toHaveBeenCalledTimes(1);
	});

	it("isRedirecting returns true during redirect", async () => {
		setAuthRedirectHandler(() => {});
		mockFetch.mockResolvedValueOnce(jsonResponse(401));

		const client = createServerApiClient("http://api.test", "tok");
		expect(isRedirecting()).toBe(false);
		await expect(client.get("/x")).rejects.toThrow(AuthError);
		expect(isRedirecting()).toBe(true);

		resetRedirectGate();
		expect(isRedirecting()).toBe(false);
	});
});

describe("409 conflict handling", () => {
	it("throws ConflictError with currentVersion on 409", async () => {
		mockFetch.mockResolvedValueOnce(
			jsonResponse(409, { detail: "Stale version", current_version: 5 }),
		);

		const client = createServerApiClient("http://api.test", "tok");
		try {
			await client.patch("/config/1", { value: "new" });
			expect.unreachable("should have thrown");
		} catch (err) {
			expect(err).toBeInstanceOf(ConflictError);
			expect((err as ConflictError).currentVersion).toBe(5);
			expect((err as ConflictError).message).toBe("Stale version");
		}
	});

	it("calls conflict handler on 409", async () => {
		const handler = vi.fn();
		setConflictHandler(handler);

		mockFetch.mockResolvedValueOnce(
			jsonResponse(409, { detail: "Updated by another user" }),
		);

		const client = createServerApiClient("http://api.test", "tok");
		await expect(client.patch("/config/1", {})).rejects.toThrow(ConflictError);

		expect(handler).toHaveBeenCalledWith("Updated by another user");
	});

	it("uses default message when detail is missing", async () => {
		mockFetch.mockResolvedValueOnce(jsonResponse(409, {}));

		const client = createServerApiClient("http://api.test", "tok");
		try {
			await client.patch("/config/1", {});
			expect.unreachable("should have thrown");
		} catch (err) {
			expect((err as ConflictError).message).toBe(
				"Resource was modified by another user",
			);
		}
	});
});

describe("createClientApiClient", () => {
	it("calls getToken for each request", async () => {
		const getToken = vi.fn().mockResolvedValue("dynamic-tok");
		mockFetch.mockResolvedValueOnce(jsonResponse(200, {}));

		const client = createClientApiClient("http://api.test", getToken);
		await client.get("/items");

		expect(getToken).toHaveBeenCalledOnce();
		const [, opts] = mockFetch.mock.calls[0]!;
		expect(opts.headers.Authorization).toBe("Bearer dynamic-tok");
	});
});
