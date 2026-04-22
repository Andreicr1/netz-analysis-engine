export interface RegimePinState {
	g: number;
	i: number;
}

export interface RegimeTrailPoint {
	as_of_date: string;
	g: number;
	i: number;
	stress?: number | null;
}

export function createRegimePlotStore() {
	let simPin = $state<RegimePinState | null>(null);

	return {
		get simPin() {
			return simPin;
		},
		set(pin: RegimePinState | null) {
			simPin = pin;
		},
		reset() {
			simPin = null;
		},
	};
}
