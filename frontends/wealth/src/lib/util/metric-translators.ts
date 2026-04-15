/**
 * metric-translators — PR-A5 Section C.
 *
 * Sanitisation-aware rendering helpers. The backend
 * (``construction_run_executor._publish_event_sanitized``) already
 * humanises the ``type`` and ``message`` fields of every SSE event;
 * the frontend renders those verbatim. The raw quant numbers survive
 * inside ``payload.metrics`` so the UI can surface secondary chips
 * that translate the numbers into PT-BR institutional labels next to
 * (not replacing) the formatted value.
 *
 * Every translator is a pure function ``(value) => TranslatedMetric``.
 * Translators NEVER format numbers — callers use ``@investintell/ui``
 * formatters for the raw value and place it alongside the chip.
 *
 * Thresholds come directly from the Section C table of the PR-A5
 * spec (``docs/prompts/2026-04-15-construction-engine-pr-a5-frontend-migration.md``).
 * Do not tune thresholds locally — surface a spec-change request if a
 * value looks wrong.
 */

export type Tone = "success" | "neutral" | "warning" | "danger";

export interface TranslatedMetric {
	label: string;
	tone: Tone;
}

/**
 * ``kappa`` — condition number of the covariance matrix (Ledoit-Wolf
 * regularised). Read: higher = less stable. Backend already falls back
 * to a heuristic when κ explodes; we surface the tone so the PM knows
 * why the numbers might look different than expected.
 */
export function translateKappa(value: number): TranslatedMetric {
	if (value < 1e4) {
		return { label: "Boa estabilidade do modelo de risco", tone: "success" };
	}
	if (value < 1e6) {
		return { label: "Estabilidade aceitável", tone: "neutral" };
	}
	return {
		label: "Atenção: modelo instável — considere regime override",
		tone: "warning",
	};
}

/**
 * ``shrinkage_lambda`` — Ledoit-Wolf shrinkage intensity in [0, 1].
 * 0 = sample covariance, 1 = pure diagonal target. Institutional
 * sweet spot is the mid-range; extremes warrant a human note.
 */
export function translateShrinkageLambda(value: number): TranslatedMetric {
	if (value < 0.15) {
		return { label: "Estimativa direta", tone: "neutral" };
	}
	if (value <= 0.7) {
		return { label: "Estimativa robusta", tone: "success" };
	}
	return {
		label: "Forte shrinkage — covariância quase diagonal",
		tone: "warning",
	};
}

/**
 * ``regime`` — detected macro regime label from the regime detector.
 * Unknown regimes pass through as a neutral default; never throw.
 */
export function translateRegime(value: string): TranslatedMetric {
	switch (value) {
		case "NORMAL":
			return { label: "Regime normal", tone: "neutral" };
		case "RISK_ON":
			return { label: "Regime expansionista", tone: "success" };
		case "RISK_OFF":
			return { label: "Regime defensivo ativo", tone: "warning" };
		case "CRISIS":
			return { label: "Regime de crise — CVaR reforçado", tone: "danger" };
		case "INFLATION":
			return { label: "Regime inflacionário", tone: "warning" };
		default:
			return { label: `Regime ${value}`, tone: "neutral" };
	}
}

/**
 * ``regime_multiplier`` — CVaR multiplier applied when the detected
 * regime tightens the risk budget. ``1.0`` means no adjustment — the
 * caller should hide the chip in that case (return ``null``).
 */
export function translateRegimeMultiplier(
	value: number,
): TranslatedMetric | null {
	if (value === 1.0) return null;
	const pct = Math.round((1 - value) * 100);
	if (value < 1.0) {
		return {
			label: `Tolerância a risco reduzida em ${pct}%`,
			tone: "warning",
		};
	}
	const loosePct = Math.round((value - 1) * 100);
	return {
		label: `Tolerância a risco ampliada em ${loosePct}%`,
		tone: "neutral",
	};
}

/**
 * ``k_factors_effective`` vs ``k_factors`` — PCA factor model coverage.
 * Flag when effective < 75% of total, so the analyst knows the
 * benchmark set collapsed.
 */
export function translateFactorCoverage(
	effective: number,
	total: number,
): TranslatedMetric {
	if (total <= 0) {
		return {
			label: "Cobertura de fatores indisponível",
			tone: "warning",
		};
	}
	if (effective >= 0.75 * total) {
		return {
			label: `${effective} de ${total} fatores ativos`,
			tone: "success",
		};
	}
	return {
		label: `Cobertura de fatores limitada (${effective} de ${total})`,
		tone: "warning",
	};
}

/**
 * ``r_squared_p50`` — median explanatory power of the factor model
 * across funds. Anchors the "how well does the risk model describe my
 * universe" question.
 */
export function translateRSquaredMedian(value: number): TranslatedMetric {
	if (value >= 0.7) {
		return { label: "Aderência média: alta", tone: "success" };
	}
	if (value >= 0.4) {
		return { label: "Aderência média: moderada", tone: "neutral" };
	}
	return {
		label: "Aderência média: baixa — revisar benchmarks",
		tone: "warning",
	};
}

/**
 * ``phase_used`` — which optimiser cascade phase produced the final
 * weights. Falling through to the heuristic is a visible signal that
 * the convex solvers could not land a feasible point.
 */
export function translateOptimizerPhase(value: string): TranslatedMetric {
	switch (value) {
		case "primary":
			return { label: "Otimizador principal", tone: "success" };
		case "robust":
			return { label: "Otimizador robusto", tone: "success" };
		case "variance_capped":
			return { label: "Variância limitada", tone: "neutral" };
		case "min_variance":
			return { label: "Variância mínima", tone: "neutral" };
		case "heuristic":
			return { label: "Fallback heurístico", tone: "warning" };
		default:
			return { label: `Otimizador: ${value}`, tone: "neutral" };
	}
}

/**
 * ``cvar_95`` (portfolio) — the tail loss at 95% confidence. Returns a
 * tone driven by whether the realised CVaR is within the mandate cap.
 * The caller renders the raw percentage via ``formatPercent``; this
 * helper only picks the chip tone. Passing ``mandateLimit = null``
 * yields a neutral tone (mandate not configured).
 *
 * CVaR is intentionally exposed as a term (Andrei's audience knows the
 * acronym — see Section C "CVaR labelling exception").
 */
export function translateCvar(
	value: number,
	mandateLimit: number | null,
): TranslatedMetric {
	if (mandateLimit == null) {
		return { label: "CVaR 95%", tone: "neutral" };
	}
	const breach = Math.abs(value) > Math.abs(mandateLimit);
	if (breach) {
		return { label: "CVaR 95% acima do limite do mandato", tone: "danger" };
	}
	const headroom = Math.abs(mandateLimit) - Math.abs(value);
	const tight = headroom < 0.1 * Math.abs(mandateLimit);
	return {
		label: tight
			? "CVaR 95% próximo ao limite do mandato"
			: "CVaR 95% dentro do mandato",
		tone: tight ? "warning" : "success",
	};
}

/**
 * ``max_drawdown_pct`` — worst historical drawdown observed in the
 * backtest. Same contract as ``translateCvar``: caller formats the raw
 * number; this helper picks the tone.
 */
export function translateMaxDrawdown(
	value: number,
	mandateLimit: number | null,
): TranslatedMetric {
	if (mandateLimit == null) {
		return { label: "Drawdown máximo", tone: "neutral" };
	}
	const breach = Math.abs(value) > Math.abs(mandateLimit);
	if (breach) {
		return {
			label: "Drawdown máximo acima do limite do mandato",
			tone: "danger",
		};
	}
	const headroom = Math.abs(mandateLimit) - Math.abs(value);
	const tight = headroom < 0.1 * Math.abs(mandateLimit);
	return {
		label: tight
			? "Drawdown máximo próximo ao limite"
			: "Drawdown máximo dentro do mandato",
		tone: tight ? "warning" : "success",
	};
}
