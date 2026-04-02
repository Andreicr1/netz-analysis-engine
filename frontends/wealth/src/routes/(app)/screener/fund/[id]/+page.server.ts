import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';

export const load: PageServerLoad = async ({ params, fetch }) => {
    const { id } = params;
    
    const res = await fetch(`/api/v1/screener/catalog/${id}/fact-sheet`);
    
    if (!res.ok) {
        if (res.status === 404) {
            throw error(404, 'Fund not found');
        }
        throw error(500, 'Failed to load fund fact sheet');
    }
    
    const factSheet = await res.json();
    
    return {
        factSheet
    };
};
