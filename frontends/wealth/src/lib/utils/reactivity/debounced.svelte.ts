/**
 * Debounced reactive state — updates the optimized value only after
 * the caller stops changing `current` for `delay` ms.
 *
 * Usage:
 *   const search = createDebouncedState("", 300);
 *   // bind:value={search.current}   ← instant for UI
 *   // use search.debounced           ← delayed for expensive ops
 */
export function createDebouncedState<T>(init: T, delay: number) {
	let _current = $state<T>(init);
	let _debounced = $state<T>(init);
	let _timer: ReturnType<typeof setTimeout> | undefined;

	$effect(() => {
		// Track `_current` — schedule debounced update
		const val = _current;
		clearTimeout(_timer);
		_timer = setTimeout(() => {
			_debounced = val;
		}, delay);

		return () => clearTimeout(_timer);
	});

	return {
		get current() {
			return _current;
		},
		set current(v: T) {
			_current = v;
		},
		get debounced() {
			return _debounced;
		},
		/** Cancel pending debounce timer. */
		cancel() {
			clearTimeout(_timer);
		},
		/** Immediately push current value to debounced (e.g. on Enter). */
		flush() {
			clearTimeout(_timer);
			_debounced = _current;
		},
	};
}
