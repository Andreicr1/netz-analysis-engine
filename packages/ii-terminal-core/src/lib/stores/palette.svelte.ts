export class PaletteState {
	isOpen = $state(false);
	query = $state("");
	selectedIndex = $state(0);

	open() {
		this.isOpen = true;
	}

	close() {
		this.isOpen = false;
		this.query = "";
		this.selectedIndex = 0;
	}

	toggle(force?: boolean) {
		const next = force ?? !this.isOpen;
		if (next) {
			this.isOpen = true;
			return;
		}
		this.close();
	}

	setQuery(query: string) {
		this.query = query;
		this.selectedIndex = 0;
	}

	setSelectedIndex(index: number) {
		this.selectedIndex = index;
	}
}

export const palette = new PaletteState();

export function openPalette() {
	palette.open();
}

export function closePalette() {
	palette.close();
}

export function togglePalette(force?: boolean) {
	palette.toggle(force);
}

export function setPaletteQuery(query: string) {
	palette.setQuery(query);
}

export function setPaletteSelectedIndex(index: number) {
	palette.setSelectedIndex(index);
}
