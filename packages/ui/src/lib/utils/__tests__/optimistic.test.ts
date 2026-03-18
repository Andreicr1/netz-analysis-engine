import { describe, expect, it } from "vitest";
import { createOptimisticMutation } from "../optimistic.svelte.js";

describe("createOptimisticMutation", () => {
	it("applies optimistic state immediately and keeps the server response", async () => {
		let state = { status: "idle" };

		const mutation = createOptimisticMutation({
			getState: () => state,
			setState: (value) => {
				state = value;
			},
			request: async () => ({ status: "confirmed" }),
		});

		const promise = mutation.mutate({ status: "pending" });

		expect(state.status).toBe("pending");
		expect(mutation.isPending).toBe(true);

		await promise;

		expect(state.status).toBe("confirmed");
		expect(mutation.isPending).toBe(false);
		expect(mutation.error).toBeNull();
	});

	it("rolls back state and exposes the error on failure", async () => {
		let state = { status: "idle" };

		const mutation = createOptimisticMutation({
			getState: () => state,
			setState: (value) => {
				state = value;
			},
			request: async () => {
				throw new Error("Save failed");
			},
		});

		await expect(mutation.mutate({ status: "pending" })).rejects.toThrow("Save failed");

		expect(state.status).toBe("idle");
		expect(mutation.isPending).toBe(false);
		expect(mutation.error).toBe("Save failed");
	});
});
