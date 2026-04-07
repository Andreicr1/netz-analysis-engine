/**
 * Throttled reactive state — ensures the optimized value updates
 * at most once every `limit` ms, with configurable leading/trailing edges.
 *
 * Usage:
 *   const scroll = createThrottledState(0, 100);
 *   // scroll.current = window.scrollY;   ← high frequency
 *   // use scroll.throttled                ← rate-limited
 */
export function createThrottledState<T>(
	init: T,
	limit: number,
	options: { leading?: boolean; trailing?: boolean } = {},
) {
	const { leading = true, trailing = true } = options;

	let _current = $state<T>(init);
	let _throttled = $state<T>(init);
	let _timer: ReturnType<typeof setTimeout> | undefined;
	let _lastExec = 0;

	$effect(() => {
		const val = _current;
		const now = Date.now();
		const elapsed = now - _lastExec;

		if (elapsed >= limit && leading) {
			_throttled = val;
			_lastExec = now;
		} else if (trailing) {
			clearTimeout(_timer);
			const remaining = limit - elapsed;
			_timer = setTimeout(() => {
				_throttled = val;
				_lastExec = Date.now();
			}, remaining > 0 ? remaining : 0);
		}

		return () => clearTimeout(_timer);
	});

	return {
		get current() {
			return _current;
		},
		set current(v: T) {
			_current = v;
		},
		get throttled() {
			return _throttled;
		},
		/** Cancel pending trailing update. */
		cancel() {
			clearTimeout(_timer);
		},
		/** Immediately push current value to throttled. */
		flush() {
			clearTimeout(_timer);
			_throttled = _current;
			_lastExec = Date.now();
		},
	};
}
