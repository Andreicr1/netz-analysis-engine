/**
 * Wealth Library — pins client with optimistic mutations.
 *
 * Phase 6 of the Library frontend (spec §3.4 Fase 6 + §4.4). Owns
 * the pinned / starred / recent lists displayed by
 * `LibraryPinsSection` and the per-row pin/star toggles emitted by
 * the context menu.
 *
 * Optimistic discipline
 * ---------------------
 * Every toggle mutates the local $state synchronously so the row
 * re-renders before the network call returns. The network call
 * runs in the background; if it fails, the change is rolled back
 * and an error string is exposed via `state.lastError` so the
 * shell can surface a toast. Concurrent toggles on the same row
 * are guarded by a tiny pending Set keyed off
 * `(pin_type, library_index_id)` so the user can't double-click
 * the same star into a busy loop.
 *
 * The client is created once per LibraryShell mount via
 * `createPinsClient(getToken)` and disposed in onDestroy.
 */

import { createClientApiClient } from "$wealth/api/client";
import type {
	LibraryPin,
	LibraryPinType,
	LibraryPinsResponse,
} from "$wealth/types/library";

export interface PinsState {
	loading: boolean;
	error: string | null;
	lastError: string | null;
	pinned: LibraryPin[];
	starred: LibraryPin[];
	recent: LibraryPin[];
}

export interface PinsClient {
	readonly state: PinsState;
	load(): Promise<void>;
	togglePin(libraryIndexId: string, label: string, kind?: string | null): Promise<void>;
	toggleStar(libraryIndexId: string, label: string, kind?: string | null): Promise<void>;
	isPinned(libraryIndexId: string): boolean;
	isStarred(libraryIndexId: string): boolean;
	dispose(): void;
}

function makeOptimisticPin(
	libraryIndexId: string,
	pinType: LibraryPinType,
	label: string,
	kind: string | null,
): LibraryPin {
	const now = new Date().toISOString();
	return {
		id: `optimistic:${pinType}:${libraryIndexId}`,
		pin_type: pinType,
		library_index_id: libraryIndexId,
		library_path: "",
		label,
		kind: kind ?? null,
		created_at: now,
		last_accessed_at: now,
		position: null,
	};
}

export function createPinsClient(
	getToken: () => Promise<string>,
): PinsClient {
	const state = $state<PinsState>({
		loading: false,
		error: null,
		lastError: null,
		pinned: [],
		starred: [],
		recent: [],
	});

	const api = createClientApiClient(getToken);
	const pending = new Set<string>();
	let disposed = false;

	function pendingKey(pinType: LibraryPinType, libraryIndexId: string): string {
		return `${pinType}:${libraryIndexId}`;
	}

	async function load(): Promise<void> {
		state.loading = true;
		state.error = null;
		try {
			const data = await api.get<LibraryPinsResponse>("/library/pins");
			if (disposed) return;
			state.pinned = data.pinned;
			state.starred = data.starred;
			state.recent = data.recent;
		} catch (err: unknown) {
			if (disposed) return;
			state.error =
				err instanceof Error ? err.message : "Failed to load pins.";
		} finally {
			if (!disposed) state.loading = false;
		}
	}

	function listFor(pinType: LibraryPinType): LibraryPin[] {
		switch (pinType) {
			case "pinned":
				return state.pinned;
			case "starred":
				return state.starred;
			case "recent":
				return state.recent;
		}
	}

	function setListFor(pinType: LibraryPinType, list: LibraryPin[]): void {
		switch (pinType) {
			case "pinned":
				state.pinned = list;
				return;
			case "starred":
				state.starred = list;
				return;
			case "recent":
				state.recent = list;
				return;
		}
	}

	async function toggle(
		pinType: LibraryPinType,
		libraryIndexId: string,
		label: string,
		kind: string | null,
	): Promise<void> {
		const key = pendingKey(pinType, libraryIndexId);
		if (pending.has(key)) return;
		pending.add(key);

		const before = listFor(pinType);
		const existing = before.find(
			(p) => p.library_index_id === libraryIndexId,
		);

		try {
			if (existing) {
				// Optimistic remove
				setListFor(
					pinType,
					before.filter(
						(p) => p.library_index_id !== libraryIndexId,
					),
				);
				try {
					await api.delete(`/library/pins/${existing.id}`);
				} catch (err) {
					// Roll back
					setListFor(pinType, before);
					state.lastError =
						err instanceof Error
							? err.message
							: "Failed to remove pin.";
				}
			} else {
				// Optimistic add
				const placeholder = makeOptimisticPin(
					libraryIndexId,
					pinType,
					label,
					kind,
				);
				setListFor(pinType, [placeholder, ...before]);
				try {
					const created = await api.post<LibraryPin>("/library/pins", {
						library_index_id: libraryIndexId,
						pin_type: pinType,
					});
					// Replace placeholder with the server's authoritative row
					setListFor(
						pinType,
						listFor(pinType).map((p) =>
							p.id === placeholder.id ? created : p,
						),
					);
				} catch (err) {
					setListFor(pinType, before);
					state.lastError =
						err instanceof Error
							? err.message
							: "Failed to create pin.";
				}
			}
		} finally {
			pending.delete(key);
		}
	}

	function togglePin(
		libraryIndexId: string,
		label: string,
		kind: string | null = null,
	): Promise<void> {
		return toggle("pinned", libraryIndexId, label, kind);
	}

	function toggleStar(
		libraryIndexId: string,
		label: string,
		kind: string | null = null,
	): Promise<void> {
		return toggle("starred", libraryIndexId, label, kind);
	}

	function isPinned(libraryIndexId: string): boolean {
		return state.pinned.some((p) => p.library_index_id === libraryIndexId);
	}

	function isStarred(libraryIndexId: string): boolean {
		return state.starred.some((p) => p.library_index_id === libraryIndexId);
	}

	function dispose(): void {
		disposed = true;
		pending.clear();
	}

	return {
		get state() {
			return state;
		},
		load,
		togglePin,
		toggleStar,
		isPinned,
		isStarred,
		dispose,
	};
}
