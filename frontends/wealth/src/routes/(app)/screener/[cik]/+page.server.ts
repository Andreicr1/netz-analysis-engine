import { redirect } from '@sveltejs/kit';

export const load = async ({ params }: { params: { cik: string } }) => {
	redirect(301, `/screener/fund/${params.cik}`);
};
