import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import FlexibleColumnLayout from './FlexibleColumnLayout.svelte';

test('expand-1 state hides col2 and col3', () => {
	const { container } = render(FlexibleColumnLayout, {
		props: {
			state: 'expand-1',
			column1Label: 'List',
			column2Label: 'Detail',
			column3Label: 'Sub-detail',
		},
	});
	const root = container.querySelector('.fcl-root') as HTMLElement;
	expect(root.style.gridTemplateColumns).toContain('0fr');
	expect(root.dataset.state).toBe('expand-1');
});

test('custom ratios override defaults', () => {
	const { container } = render(FlexibleColumnLayout, {
		props: {
			state: 'expand-3',
			ratios: { 'expand-3': [0.1, 0.3, 0.6] },
			column1Label: 'A',
			column2Label: 'B',
			column3Label: 'C',
		},
	});
	const root = container.querySelector('.fcl-root') as HTMLElement;
	expect(root.style.gridTemplateColumns).toContain('0.1fr');
	expect(root.style.gridTemplateColumns).toContain('0.6fr');
});
