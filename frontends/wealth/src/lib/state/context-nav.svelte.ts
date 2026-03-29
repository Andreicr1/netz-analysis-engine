import { getContext, setContext } from "svelte";
import type { ContextNav } from "@investintell/ui/utils";

const KEY = Symbol("netz:contextNav");

interface ContextNavState {
	current: ContextNav | null;
}

/** Call once in root +layout.svelte to create the per-request instance. */
export function initContextNav(): ContextNavState {
	const state: ContextNavState = $state({ current: null });
	setContext(KEY, state);
	return state;
}

/** Call in any descendant layout/component to read or write contextNav. */
export function useContextNav(): ContextNavState {
	return getContext<ContextNavState>(KEY);
}
