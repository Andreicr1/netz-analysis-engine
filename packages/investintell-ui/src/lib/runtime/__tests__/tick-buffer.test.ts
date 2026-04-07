import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createTickBuffer } from "../tick-buffer.svelte";

interface Tick {
	ticker: string;
	price: number;
}

const keyOf = (t: Tick) => t.ticker;

describe("createTickBuffer — config", () => {
	it("rejects non-positive maxKeys", () => {
		expect(() =>
			createTickBuffer<Tick>({ keyOf, maxKeys: 0 }),
		).toThrowError(/maxKeys/);
	});
});

describe("createTickBuffer — write semantics", () => {
	it("coalesces same-key writes into one snapshot entry", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 10_000 },
		});
		buf.write({ ticker: "SPY", price: 1 });
		buf.write({ ticker: "SPY", price: 2 });
		buf.write({ ticker: "SPY", price: 3 });
		buf.flush();
		expect(buf.snapshot.size).toBe(1);
		expect(buf.snapshot.get("SPY")?.price).toBe(3);
		expect(buf.written).toBe(3);
		buf.dispose();
	});

	it("tracks multiple distinct keys", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 10_000 },
		});
		buf.write({ ticker: "SPY", price: 1 });
		buf.write({ ticker: "QQQ", price: 2 });
		buf.write({ ticker: "IWM", price: 3 });
		buf.flush();
		expect(buf.snapshot.size).toBe(3);
		expect(buf.snapshot.get("QQQ")?.price).toBe(2);
		buf.dispose();
	});

	it("accepts writeMany", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 10_000 },
		});
		buf.writeMany([
			{ ticker: "A", price: 1 },
			{ ticker: "B", price: 2 },
			{ ticker: "A", price: 3 },
		]);
		buf.flush();
		expect(buf.snapshot.size).toBe(2);
		expect(buf.snapshot.get("A")?.price).toBe(3);
		buf.dispose();
	});
});

describe("createTickBuffer — eviction", () => {
	it("drops oldest when maxKeys exceeded (drop_oldest default)", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			maxKeys: 2,
			clock: { intervalMs: 10_000 },
		});
		buf.write({ ticker: "A", price: 1 });
		buf.write({ ticker: "B", price: 2 });
		buf.write({ ticker: "C", price: 3 });
		buf.flush();
		expect(buf.snapshot.size).toBe(2);
		expect(buf.snapshot.has("A")).toBe(false);
		expect(buf.snapshot.has("B")).toBe(true);
		expect(buf.snapshot.has("C")).toBe(true);
		expect(buf.dropped).toBe(1);
		buf.dispose();
	});

	it("drops newest when drop_newest policy set", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			maxKeys: 2,
			evictionPolicy: "drop_newest",
			clock: { intervalMs: 10_000 },
		});
		buf.write({ ticker: "A", price: 1 });
		buf.write({ ticker: "B", price: 2 });
		buf.write({ ticker: "C", price: 3 });
		buf.flush();
		expect(buf.snapshot.has("A")).toBe(true);
		expect(buf.snapshot.has("B")).toBe(true);
		expect(buf.snapshot.has("C")).toBe(false);
		expect(buf.dropped).toBe(1);
		buf.dispose();
	});

	it("updating an existing key never evicts", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			maxKeys: 2,
			clock: { intervalMs: 10_000 },
		});
		buf.write({ ticker: "A", price: 1 });
		buf.write({ ticker: "B", price: 2 });
		buf.write({ ticker: "A", price: 99 });
		buf.flush();
		expect(buf.snapshot.size).toBe(2);
		expect(buf.dropped).toBe(0);
		expect(buf.snapshot.get("A")?.price).toBe(99);
		buf.dispose();
	});
});

describe("createTickBuffer — clock + pause", () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("interval clock flushes on schedule", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 250 },
		});
		buf.write({ ticker: "SPY", price: 1 });
		expect(buf.snapshot.size).toBe(0); // not yet flushed
		vi.advanceTimersByTime(260);
		expect(buf.snapshot.size).toBe(1);
		buf.dispose();
	});

	it("pause stops flushes but keeps writes", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 100 },
		});
		buf.pause();
		buf.write({ ticker: "SPY", price: 1 });
		vi.advanceTimersByTime(500);
		expect(buf.snapshot.size).toBe(0);
		buf.resume();
		// Resume triggers an immediate flush of pending writes.
		expect(buf.snapshot.size).toBe(1);
		buf.dispose();
	});

	it("dispose stops the clock and clears state", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 100 },
		});
		buf.write({ ticker: "SPY", price: 1 });
		buf.dispose();
		vi.advanceTimersByTime(500);
		expect(buf.snapshot.size).toBe(0);
		// Subsequent writes are no-ops.
		buf.write({ ticker: "QQQ", price: 2 });
		expect(buf.snapshot.size).toBe(0);
	});
});

describe("createTickBuffer — coalescing behaviour", () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("500 writes produce exactly one snapshot update per flush", () => {
		const buf = createTickBuffer<Tick>({
			keyOf,
			clock: { intervalMs: 100 },
		});
		const initial = buf.snapshot;
		for (let i = 0; i < 500; i++) {
			buf.write({ ticker: `T${i % 10}`, price: i });
		}
		// Still the initial (empty) snapshot — no flush fired yet.
		expect(buf.snapshot).toBe(initial);
		vi.advanceTimersByTime(150);
		// After the flush, snapshot has been replaced exactly once.
		expect(buf.snapshot).not.toBe(initial);
		expect(buf.snapshot.size).toBe(10);
		buf.dispose();
	});
});
