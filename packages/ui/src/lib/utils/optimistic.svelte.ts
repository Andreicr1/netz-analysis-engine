export interface OptimisticMutationConfig<T> {
	getState: () => T;
	setState: (value: T) => void;
	request: (optimisticValue: T, previousValue: T) => Promise<T>;
}

export interface OptimisticMutation<T> {
	mutate: (optimisticValue: T) => Promise<T>;
	rollback: () => void;
	readonly isPending: boolean;
	readonly error: string | null;
}

function cloneValue<T>(value: T): T {
	try {
		return structuredClone(value);
	} catch {
		return value;
	}
}

export function createOptimisticMutation<T>(
	config: OptimisticMutationConfig<T>,
): OptimisticMutation<T> {
	let isPending = $state(false);
	let error = $state<string | null>(null);
	let snapshot = $state<T | null>(null);

	function rollback() {
		if (snapshot === null) {
			return;
		}

		config.setState(cloneValue(snapshot));
		snapshot = null;
		isPending = false;
	}

	async function mutate(optimisticValue: T): Promise<T> {
		const previousValue = cloneValue(config.getState());
		snapshot = previousValue;
		error = null;
		isPending = true;
		config.setState(optimisticValue);

		try {
			const result = await config.request(optimisticValue, previousValue);
			config.setState(result);
			snapshot = null;
			return result;
		} catch (reason) {
			rollback();
			error = reason instanceof Error ? reason.message : "Optimistic mutation failed";
			throw reason;
		} finally {
			isPending = false;
		}
	}

	return {
		mutate,
		rollback,
		get isPending() {
			return isPending;
		},
		get error() {
			return error;
		},
	};
}
