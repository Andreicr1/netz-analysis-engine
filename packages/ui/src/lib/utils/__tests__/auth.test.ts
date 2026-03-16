import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { startSessionExpiryMonitor } from "../auth.js";

/** Create a minimal JWT with the given exp (Unix seconds). */
function makeJwt(exp: number): string {
	const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
	const payload = btoa(JSON.stringify({ exp, sub: "user1" }));
	return `${header}.${payload}.signature`;
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

describe("startSessionExpiryMonitor", () => {
	it("fires warning 5 minutes before expiry", () => {
		const onWarning = vi.fn();
		const now = Date.now();
		// Token expires in 10 minutes
		const exp = Math.floor((now + 10 * 60 * 1000) / 1000);
		const token = makeJwt(exp);

		const cleanup = startSessionExpiryMonitor(token, onWarning);

		// At 4 minutes — should not have fired
		vi.advanceTimersByTime(4 * 60 * 1000);
		expect(onWarning).not.toHaveBeenCalled();

		// At 5 minutes — should fire (10min - 5min warning = 5min delay)
		vi.advanceTimersByTime(1 * 60 * 1000);
		expect(onWarning).toHaveBeenCalledOnce();

		cleanup();
	});

	it("fires immediately when already within warning window", () => {
		const onWarning = vi.fn();
		const now = Date.now();
		// Token expires in 2 minutes (already within 5min window)
		const exp = Math.floor((now + 2 * 60 * 1000) / 1000);
		const token = makeJwt(exp);

		startSessionExpiryMonitor(token, onWarning);

		// Should fire immediately (synchronously)
		expect(onWarning).toHaveBeenCalledOnce();
	});

	it("fires immediately when token is already expired", () => {
		const onWarning = vi.fn();
		const now = Date.now();
		// Token already expired 1 minute ago
		const exp = Math.floor((now - 60 * 1000) / 1000);
		const token = makeJwt(exp);

		startSessionExpiryMonitor(token, onWarning);

		expect(onWarning).toHaveBeenCalledOnce();
	});

	it("handles custom warning threshold", () => {
		const onWarning = vi.fn();
		const now = Date.now();
		// Expires in 15 minutes, warn 10 minutes before
		const exp = Math.floor((now + 15 * 60 * 1000) / 1000);
		const token = makeJwt(exp);

		const cleanup = startSessionExpiryMonitor(
			token,
			onWarning,
			10 * 60 * 1000,
		);

		// At 4 minutes — should not have fired
		vi.advanceTimersByTime(4 * 60 * 1000);
		expect(onWarning).not.toHaveBeenCalled();

		// At 5 minutes — should fire (15min - 10min warning = 5min delay)
		vi.advanceTimersByTime(1 * 60 * 1000);
		expect(onWarning).toHaveBeenCalledOnce();

		cleanup();
	});

	it("cleanup cancels the timer", () => {
		const onWarning = vi.fn();
		const now = Date.now();
		const exp = Math.floor((now + 10 * 60 * 1000) / 1000);
		const token = makeJwt(exp);

		const cleanup = startSessionExpiryMonitor(token, onWarning);
		cleanup();

		// Advance past when it would have fired
		vi.advanceTimersByTime(10 * 60 * 1000);
		expect(onWarning).not.toHaveBeenCalled();
	});

	it("does not crash on malformed token", () => {
		const onWarning = vi.fn();

		// Various malformed tokens
		expect(() => startSessionExpiryMonitor("", onWarning)).not.toThrow();
		expect(() => startSessionExpiryMonitor("not.a.jwt", onWarning)).not.toThrow();
		expect(() => startSessionExpiryMonitor("a.b", onWarning)).not.toThrow();
		expect(() => startSessionExpiryMonitor("a.b.c.d", onWarning)).not.toThrow();

		expect(onWarning).not.toHaveBeenCalled();
	});

	it("does not crash when exp claim is missing", () => {
		const onWarning = vi.fn();
		const header = btoa(JSON.stringify({ alg: "HS256" }));
		const payload = btoa(JSON.stringify({ sub: "user1" })); // no exp
		const token = `${header}.${payload}.sig`;

		expect(() => startSessionExpiryMonitor(token, onWarning)).not.toThrow();
		expect(onWarning).not.toHaveBeenCalled();
	});

	it("does not crash when exp is not a number", () => {
		const onWarning = vi.fn();
		const header = btoa(JSON.stringify({ alg: "HS256" }));
		const payload = btoa(JSON.stringify({ exp: "not-a-number" }));
		const token = `${header}.${payload}.sig`;

		expect(() => startSessionExpiryMonitor(token, onWarning)).not.toThrow();
		expect(onWarning).not.toHaveBeenCalled();
	});
});
