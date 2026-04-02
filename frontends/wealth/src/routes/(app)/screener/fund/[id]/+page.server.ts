import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { createServerApiClient } from '$lib/api/client';

export const load: PageServerLoad = async ({ params, parent }) => {
    const { id } = params;
    const { token } = await parent();
    const api = createServerApiClient(token);

    try {
        const factSheet = await api.get(`/screener/catalog/${id}/fact-sheet`);
        return { factSheet };
    } catch (err: unknown) {
        if (err && typeof err === 'object' && 'status' in err) {
            const status = (err as { status: number }).status;
            if (status === 404) throw error(404, 'Fund not found');
            throw error(status, 'Failed to load fund data');
        }
        throw error(500, 'Failed to load fund data');
    }
};
