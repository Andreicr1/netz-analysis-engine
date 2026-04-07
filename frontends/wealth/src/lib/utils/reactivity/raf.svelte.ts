/**
 * rAF-synced reactive state — batches updates to the next
 * requestAnimationFrame tick, ideal for cursor/tooltip/drag positions.
 *
 * Usage:
 *   const pos = createRafState({ x: 0, y: 0 });
 *   // onmousemove: pos.current = { x: e.clientX, y: e.clientY };
 *   // use pos.synced for rendering — always aligned to display refresh
 */
export function createRafState<T>(init: T) {
	let _current = $state<T>(init);
	let _synced = $state<T>(init);
	let _raf: number | undefined;

	$effect(() => {
		const val = _current;
		if (_raf !== undefined) cancelAnimationFrame(_raf);
		_raf = requestAnimationFrame(() => {
			_synced = val;
			_raf = undefined;
		});

		return () => {
			if (_raf !== undefined) {
				cancelAnimationFrame(_raf);
				_raf = undefined;
			}
		};
	});

	return {
		get current() {
			return _current;
		},
		set current(v: T) {
			_current = v;
		},
		get synced() {
			return _synced;
		},
		/** Cancel pending rAF. */
		cancel() {
			if (_raf !== undefined) {
				cancelAnimationFrame(_raf);
				_raf = undefined;
			}
		},
		/** Immediately sync current value (bypass rAF). */
		flush() {
			this.cancel();
			_synced = _current;
		},
	};
}
