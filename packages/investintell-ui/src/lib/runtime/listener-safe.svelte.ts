/**
 * Mounted guard — a tiny helper for async callbacks in Svelte
 * components.
 *
 * Stability Guardrails §3.3 — satisfies P4 (Lifecycle).
 *
 * Problem this solves
 * -------------------
 * Svelte 5 components tear down their reactive graph on unmount.
 * Any async callback that was registered before unmount (a store
 * subscription, a `fetch` continuation, a WebSocket `onmessage`
 * handler) may still fire after the component is gone. If that
 * callback touches `$state` on the dead component, Svelte throws a
 * "cannot update reactive graph" error that bubbles to the nearest
 * `<svelte:boundary>` — or, if none exists, to the SvelteKit error
 * boundary, producing the black-screen incident documented in §7.2
 * of the design spec.
 *
 * `createMountedGuard()` is the minimum mechanism to ask "am I
 * still mounted?" from inside a callback:
 *
 * ```ts
 * const lifecycle = createMountedGuard();
 * onMount(() => {
 *   lifecycle.start();
 *   const unsub = store.subscribe((v) => {
 *     lifecycle.guard(() => {
 *       localState = v;
 *     });
 *   });
 *   return () => {
 *     lifecycle.stop();
 *     unsub();
 *   };
 * });
 * ```
 *
 * `guard(fn)` runs `fn` only if `mounted` is still true. If the
 * component has been destroyed, `fn` is skipped and `guard` returns
 * `undefined`.
 */

export interface MountedGuard {
	readonly mounted: boolean;
	guard<T>(fn: () => T): T | undefined;
	start(): void;
	stop(): void;
}

export function createMountedGuard(): MountedGuard {
	let mounted = false;
	return {
		get mounted() {
			return mounted;
		},
		guard<T>(fn: () => T): T | undefined {
			if (!mounted) return undefined;
			return fn();
		},
		start(): void {
			mounted = true;
		},
		stop(): void {
			mounted = false;
		},
	};
}
