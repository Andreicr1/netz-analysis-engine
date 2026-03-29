"""Generate preview PDFs for all content-production engines.

Outputs to backend/.data/:
  - preview_long_form_report_{lang}.pdf
  - preview_investment_outlook_{lang}.pdf
  - preview_macro_committee_{lang}.pdf
  - preview_manager_spotlight_{lang}.pdf

Usage:
    python -m scripts.preview_content_pdfs [--language en]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vertical_engines.wealth.content_pdf import render_content_pdf
from vertical_engines.wealth.fact_sheet.i18n import Language


# ═══════════════════════════════════════════════════════════════════
#  Mock content generators
# ═══════════════════════════════════════════════════════════════════


def _long_form_report_md(lang: Language) -> tuple[str, str, str]:
    """Return (title, subtitle, markdown) for long-form report."""
    if lang == "pt":
        title = "Relatório Institucional"
        subtitle = "Netz Growth Allocation"
        md = """\
# Relatório de Due Diligence de Longo Prazo

## 1. Contexto Macroeconômico

O ambiente macroeconômico global em março de 2026 é caracterizado por uma divergência entre as políticas monetárias das principais economias. O Federal Reserve mantém uma postura cautelosa com taxas de juros em 4.25%, enquanto o BCE iniciou um ciclo de corte gradual. O crescimento do PIB dos EUA permanece resiliente em 2.3% a/a, suportado pelo consumo das famílias e investimento em IA.

Os indicadores de estresse financeiro (OFR FSI) permanecem em território neutro (-0.15), com o spread de crédito corporativo IG em 95bps — abaixo da média histórica de 120bps. O mercado imobiliário residencial dos EUA mostra sinais mistos: os índices Case-Shiller das 20 maiores metrópoles registram crescimento médio de 3.8% a/a, mas com dispersão significativa entre regiões (Sun Belt +6.2% vs. Nordeste +1.4%).

## 2. Racional de Alocação Estratégica

A alocação atual do portfólio reflete um posicionamento pró-cíclico moderado, consistente com o regime de expansão identificado pelo modelo de Markov. A sobreposição de equities (40% vs. benchmark 35%) é justificada pelo momentum positivo nos fatores de crescimento e qualidade.

**Alocação por bloco:**
- Renda Variável EUA: 40% (benchmark: 35%)
- Renda Variável Internacional: 15% (benchmark: 15%)
- Renda Fixa: 30% (benchmark: 35%)
- Crédito Privado: 10% (benchmark: 10%)
- Caixa: 5% (benchmark: 5%)

A redução de 5pp em renda fixa a favor de equities domésticos foi implementada em janeiro 2026, após confirmação do regime de expansão por três meses consecutivos.

## 3. Composição do Portfólio e Mudanças

O portfólio é composto por 8 instrumentos selecionados via processo de screening de 3 camadas (eliminatório → mandato → quantitativo). As mudanças no trimestre incluem:

- **Adição:** T. Rowe Price Growth Stock (PRGFX) — substituiu ARK Innovation (ARKK) após falha no gate de drawdown máximo
- **Redução:** PIMCO Total Return (PTTRX) de 25% → 20% — realocação para crédito privado
- **Manutenção:** VOO (25%), IEFA (15%), ARCC (10%), JPMXX (5%)

## 4. Atribuição de Performance (Brinson-Fachler)

A performance do portfólio no trimestre (+3.45%) superou o benchmark (+2.87%) em 58bps. A decomposição Brinson-Fachler revela:

- **Efeito Alocação:** +0.54% — contribuição positiva da sobreposição em equities durante rally de Q1
- **Efeito Seleção:** +1.19% — VOO (+0.82%) e ARCC (+0.15%) foram os principais contribuidores
- **Efeito Interação:** -0.10% — negativo marginal na renda fixa internacional
- **Efeito Total:** +1.65%

## 5. Decomposição de Risco (CVaR)

O CVaR 95% do portfólio é de -4.72%, inferior ao benchmark (-5.15%), indicando perfil de risco controlado. A decomposição por bloco:

- Renda Variável EUA: contribui com 62% do risco total (proporcional ao peso)
- Renda Fixa: contribui com 18% — abaixo do peso, benefício da diversificação
- Crédito Privado: contribui com 15% — acima do peso, spread risk concentrado

A correlação média entre blocos é de 0.42, com o bloco de crédito privado apresentando correlação de apenas 0.18 com equities — justificando a alocação como diversificador.

## 6. Análise de Taxas

O expense ratio médio ponderado do portfólio é de 0.45%, abaixo da mediana de mercado para portfólios multi-ativos (0.68%). O fee drag total é de 8.4% do retorno bruto anualizado.

Instrumentos com fee efficiency abaixo do limiar (>50% de drag ratio):
- T. Rowe Price Growth (PRGFX): ER 0.65%, drag ratio 52.0% — monitorar
- Fidelity Contrafund (FCNTX): ER 0.82%, drag ratio 61.0% — candidato a substituição

## 7. Destaques por Fundo

**Vanguard S&P 500 ETF (VOO)** — Tracking difference de +0.01% (favorável). ER de 0.03% é o mais baixo da carteira. Cobertura de 507 holdings com turnover de 3%. Classificação SEC: index fund, diversified.

**Ares Capital Corp (ARCC)** — BDC externally managed com foco em private credit. Net operating expenses de 1.50%. Investment focus: senior secured loans, first lien. Yield de 9.8% compensa o drag ratio mais alto.

**JPMorgan Prime Money Market (JPMXX)** — MMF categoria Government. WAM: 25 dias, WAL: 45 dias. 7-day gross yield: 4.85%. Liquidez diária: 98.2%.

## 8. Perspectiva Forward

Mantemos o posicionamento pró-cíclico moderado com viés para redução de risco caso os indicadores de regime sinalizem transição para contração. Triggers de rebalanceamento:

- Drift > 5pp em qualquer bloco → rebalanceamento automático
- Transição de regime → revisão completa da alocação
- CVaR breach > -6% → redução de equities em 5pp

O próximo review está agendado para abril 2026, após divulgação dos resultados corporativos de Q1."""
    else:
        title = "Institutional Report"
        subtitle = "Netz Growth Allocation"
        md = """\
# Long-Form Due Diligence Report

## 1. Macroeconomic Context

The global macroeconomic environment in March 2026 is characterized by divergent monetary policies across major economies. The Federal Reserve maintains a cautious stance with rates at 4.25%, while the ECB has initiated a gradual cutting cycle. US GDP growth remains resilient at 2.3% y/y, supported by household consumption and AI investment.

Financial stress indicators (OFR FSI) remain in neutral territory (-0.15), with IG corporate credit spreads at 95bps — below the historical average of 120bps. The US residential real estate market shows mixed signals: Case-Shiller indices for 20 major metros record average growth of 3.8% y/y, but with significant regional dispersion (Sun Belt +6.2% vs. Northeast +1.4%).

## 2. Strategic Allocation Rationale

The current portfolio allocation reflects a moderately pro-cyclical positioning, consistent with the expansion regime identified by the Markov model. The equity overweight (40% vs. benchmark 35%) is justified by positive momentum in growth and quality factors.

**Allocation by block:**
- US Equity: 40% (benchmark: 35%)
- International Equity: 15% (benchmark: 15%)
- Fixed Income: 30% (benchmark: 35%)
- Private Credit: 10% (benchmark: 10%)
- Cash: 5% (benchmark: 5%)

## 3. Portfolio Composition & Changes

The portfolio consists of 8 instruments selected via 3-layer screening (eliminatory → mandate → quantitative). Quarterly changes include:

- **Addition:** T. Rowe Price Growth Stock (PRGFX) — replaced ARK Innovation (ARKK) after max drawdown gate failure
- **Reduction:** PIMCO Total Return (PTTRX) from 25% → 20% — reallocation to private credit
- **Maintained:** VOO (25%), IEFA (15%), ARCC (10%), JPMXX (5%)

## 4. Performance Attribution (Brinson-Fachler)

Portfolio performance in Q1 (+3.45%) outperformed the benchmark (+2.87%) by 58bps. Brinson-Fachler decomposition reveals:

- **Allocation Effect:** +0.54%
- **Selection Effect:** +1.19%
- **Interaction Effect:** -0.10%
- **Total Effect:** +1.65%

## 5. Risk Decomposition (CVaR)

Portfolio CVaR 95% is -4.72%, better than benchmark (-5.15%), indicating controlled risk. Average cross-block correlation is 0.42.

## 6. Fee Analysis

Weighted average expense ratio is 0.45%, below the multi-asset median of 0.68%. Total fee drag is 8.4% of annualized gross return.

## 7. Per-Fund Highlights

**Vanguard S&P 500 ETF (VOO)** — Tracking difference +0.01%. ER 0.03%. 507 holdings, 3% turnover. SEC classification: index fund, diversified.

**Ares Capital Corp (ARCC)** — Externally managed BDC. Net operating expenses 1.50%. Yield 9.8%.

**JPMorgan Prime Money Market (JPMXX)** — Government MMF. WAM 25 days, WAL 45 days. 7-day yield 4.85%.

## 8. Forward Outlook

We maintain moderate pro-cyclical positioning with bias toward risk reduction if regime indicators signal contraction transition. Next review scheduled for April 2026."""

    return title, subtitle, md


def _investment_outlook_md(lang: Language) -> tuple[str, str, str]:
    """Return (title, subtitle, markdown) for investment outlook."""
    if lang == "pt":
        title = "Perspectiva de Investimento"
        subtitle = "Q2 2026"
        md = """\
## Resumo Macro Global

O cenário macroeconômico global permanece construtivo, embora com riscos assimétricos concentrados no setor de crédito corporativo e na geopolítica do Pacífico. A economia americana demonstra resiliência acima do esperado, com o mercado de trabalho em pleno emprego (desemprego 3.7%) e inflação convergindo para a meta de 2% (CPI core 2.4% a/a).

Na Europa, a retomada é gradual mas consistente: o PMI composto da zona do euro retornou ao território expansionista (51.8) pela primeira vez em 18 meses. O BCE cortou juros em 25bps para 3.50%, sinalizando mais dois cortes até o final de 2026.

A China mantém crescimento de 4.8% a/a, sustentado por estímulos fiscais direcionados e recuperação do setor imobiliário. O índice de preços de imóveis nas Tier-1 cities estabilizou após 24 meses de queda.

## Perspectiva Regional

**América do Norte:** Viés positivo. Earnings season de Q4 2025 surpreendeu em +4.2% vs. consenso. Setor de tecnologia lidera com AI capex em $180B anualizados. Risco: eleições presidenciais em novembro podem gerar volatilidade a partir de Q3.

**Europa:** Neutro para positivo. Recuperação do setor manufatureiro alemão (+1.2% m/m) e acomodação monetária do BCE. Risco: fragmentação política na França e tensões comerciais com a China.

**Ásia-Pacífico:** Neutro. Japão beneficia-se de yen fraco para exportações, mas BoJ pode surpreender com aperto monetário. Índia mantém crescimento robusto de 6.5% a/a.

**Mercados Emergentes:** Cauteloso. Diferencial de juros EUA-EM comprimido reduz atratividade de carry. Brasil beneficia-se de termos de troca favoráveis (commodities agrícolas).

## Visão por Classe de Ativos

**Renda Variável:** Overweight (+5pp). Valuations em 19.2x P/E forward nos EUA — acima da média mas suportados por crescimento de earnings de 12%. Preferência por qualidade e dividendos.

**Renda Fixa:** Underweight (-5pp). Duration curta preferida. Yield de 10Y Treasury em 4.15% oferece carry atrativo, mas risco de duration elevado em cenário de surpresa inflacionária.

**Crédito Privado:** Neutral weight. Spreads de direct lending em 550-650bps sobre SOFR permanecem atrativos vs. risco histórico de default (2.1%). Preferência por senior secured, first lien.

**Commodities:** Slight overweight. Ouro em $2,350/oz serve como hedge geopolítico. Petróleo estável em $75-85/bbl.

## Posicionamento do Portfólio

Recomendamos manutenção do posicionamento pró-cíclico moderado com as seguintes ações:

1. Manter overweight em equities americanos (qualidade + growth)
2. Iniciar posição em equities europeus (recuperação PMI)
3. Reduzir duration em renda fixa (front-end da curva)
4. Manter alocação em crédito privado (income + diversificação)
5. Adicionar hedge de ouro (2-3% do portfólio)

## Riscos Principais

1. **Inflação sticky:** CPI core acima de 3% por 2+ meses → repricing de cortes do Fed
2. **Geopolítica:** Escalada Taiwan/China → risk-off generalizado
3. **Crédito corporativo:** Ciclo de default em CCC/B → contágio para IG
4. **Eleições EUA:** Incerteza fiscal e regulatória a partir de Q3 2026
5. **AI bubble risk:** Concentração de capex em poucos players → risco de correção setorial"""
    else:
        title = "Investment Outlook"
        subtitle = "Q2 2026"
        md = """\
## Global Macro Summary

The global macroeconomic outlook remains constructive, though with asymmetric risks concentrated in corporate credit and Pacific geopolitics. The US economy demonstrates above-expected resilience, with full employment (unemployment 3.7%) and inflation converging to target (core CPI 2.4% y/y).

In Europe, recovery is gradual but consistent: the Eurozone composite PMI returned to expansionary territory (51.8) for the first time in 18 months. The ECB cut rates by 25bps to 3.50%.

## Regional Outlook

**North America:** Positive bias. Q4 2025 earnings surprised by +4.2% vs. consensus. Tech sector leads with AI capex at $180B annualized.

**Europe:** Neutral to positive. German manufacturing recovery (+1.2% m/m) and ECB accommodation.

**Asia-Pacific:** Neutral. Japan benefits from weak yen; India maintains robust 6.5% y/y growth.

## Asset Class Views

**Equities:** Overweight (+5pp). Valuations at 19.2x forward P/E — above average but supported by 12% earnings growth.

**Fixed Income:** Underweight (-5pp). Short duration preferred. 10Y Treasury at 4.15%.

**Private Credit:** Neutral. Direct lending spreads at 550-650bps over SOFR remain attractive.

## Portfolio Positioning

We recommend maintaining moderate pro-cyclical positioning with equity overweight in quality and growth factors. Reduce fixed income duration. Add gold hedge (2-3% of portfolio).

## Key Risks

1. Sticky inflation — core CPI above 3% for 2+ months
2. Geopolitics — Taiwan/China escalation
3. Corporate credit cycle — CCC/B default contagion
4. US elections — fiscal and regulatory uncertainty from Q3 2026
5. AI concentration risk — capex in few players"""

    return title, subtitle, md


def _macro_committee_md(lang: Language) -> tuple[str, str, str]:
    """Return (title, subtitle, markdown) for macro committee review."""
    if lang == "pt":
        title = "Revisão Macro Semanal"
        subtitle = "Comitê de Investimentos — 28 Mar 2026"
        md = """\
## Resumo Executivo

Revisão semanal do comitê macro identifica **mudança material** no score da região Ásia-Pacífico (-8.5 pontos) devido à reversão do BoJ na política monetária. Demais regiões permanecem estáveis. Regime global: **Expansão** (sem transição).

## Deltas de Score por Região

- **América do Norte:** 72.5 → 73.1 (+0.6) — estável, sem flag
- **Europa:** 65.8 → 66.2 (+0.4) — estável, recuperação gradual do PMI
- **Ásia-Pacífico:** 68.3 → 59.8 (-8.5) — **FLAG: mudança material** ⚠️
- **Mercados Emergentes:** 58.2 → 57.9 (-0.3) — estável
- **Global:** 66.2 → 64.3 (-1.9) — pressão de APAC

## Transições de Regime

Nenhuma transição de regime identificada nesta semana. Todos os regimes regionais permanecem inalterados:
- América do Norte: Expansão
- Europa: Expansão (desde Fev 2026)
- Ásia-Pacífico: Expansão (mas próximo do limiar de contração)
- Mercados Emergentes: Contração (desde Dez 2025)

## Indicadores Globais

- **Índice Geopolítico:** 45.2 → 48.7 (+3.5) — elevação por tensões no Mar do Sul da China
- **Energia (WTI):** $78.50 → $82.30 (+4.8%) — supply concerns OPEC+
- **Commodities (CRB):** 285.3 → 287.1 (+0.6%) — estável
- **USD (DXY):** 103.8 → 104.2 (+0.4%) — leve fortalecimento

## Alertas de Staleness

Os seguintes indicadores estão com dados atrasados (>7 dias):
- `imf_weo_gdp_forecast` — última atualização: 15 Mar 2026
- `bis_credit_gap_cn` — última atualização: 12 Mar 2026

## Recomendações do Comitê

1. **Monitorar APAC de perto** — próxima reunião do BoJ em 10 Abr pode confirmar ou reverter a tendência
2. **Manter posicionamento atual** — nenhuma ação imediata recomendada
3. **Preparar cenário de contração APAC** — simular impacto em portfólios com exposição >10% a equities japoneses
4. **Atualizar dados BIS e IMF** — solicitar refresh manual dos indicadores atrasados"""
    else:
        title = "Weekly Macro Review"
        subtitle = "Investment Committee — 28 Mar 2026"
        md = """\
## Executive Summary

Weekly macro committee review identifies **material change** in Asia-Pacific region score (-8.5 points) due to BoJ policy reversal. Other regions remain stable. Global regime: **Expansion** (no transition).

## Regional Score Deltas

- **North America:** 72.5 → 73.1 (+0.6) — stable, no flag
- **Europe:** 65.8 → 66.2 (+0.4) — stable, gradual PMI recovery
- **Asia-Pacific:** 68.3 → 59.8 (-8.5) — **FLAG: material change**
- **Emerging Markets:** 58.2 → 57.9 (-0.3) — stable
- **Global:** 66.2 → 64.3 (-1.9) — APAC pressure

## Regime Transitions

No regime transitions this week. All regional regimes unchanged:
- North America: Expansion
- Europe: Expansion (since Feb 2026)
- Asia-Pacific: Expansion (but near contraction threshold)
- Emerging Markets: Contraction (since Dec 2025)

## Global Indicators

- **Geopolitical Index:** 45.2 → 48.7 (+3.5)
- **Energy (WTI):** $78.50 → $82.30 (+4.8%)
- **Commodities (CRB):** 285.3 → 287.1 (+0.6%)
- **USD (DXY):** 103.8 → 104.2 (+0.4%)

## Staleness Alerts

- `imf_weo_gdp_forecast` — last update: 15 Mar 2026
- `bis_credit_gap_cn` — last update: 12 Mar 2026

## Committee Recommendations

1. **Monitor APAC closely** — next BoJ meeting April 10 may confirm or reverse the trend
2. **Maintain current positioning** — no immediate action recommended
3. **Prepare APAC contraction scenario** — simulate impact on portfolios with >10% Japanese equity exposure
4. **Update BIS and IMF data** — request manual refresh of stale indicators"""

    return title, subtitle, md


def _manager_spotlight_md(lang: Language) -> tuple[str, str, str]:
    """Return (title, subtitle, markdown) for manager spotlight."""
    if lang == "pt":
        title = "Destaque do Gestor"
        subtitle = "Ares Capital Corporation (ARCC)"
        md = """\
## Visão Geral do Fundo

**Ares Capital Corporation (ARCC)** é uma Business Development Company (BDC) externally managed pela Ares Management Corporation, uma das maiores gestoras de crédito alternativo do mundo com $395B em AUM (Dez 2025). A ARCC é o maior BDC listado nos EUA por ativos totais ($23.4B), focada em empréstimos diretos (direct lending) para empresas do middle market americano.

**Classificação SEC:** BDC (Business Development Company)
**Strategy Label:** Private Credit
**Expense Ratio:** 1.50% (net operating expenses)
**Gestão:** Externally managed por Ares Management (CRD: 152891)
**Investment Focus:** Senior secured, first lien — middle market ($50M-$250M EBITDA)
**Inception Date:** 2004-10-08

**Flags de Classificação:**
- Index Fund: Não
- Fund of Funds: Não
- Target Date: Não
- Securities Lending: Não autorizado

## Análise Quantitativa

**Métricas de Retorno (1Y):**
- Retorno total: +14.2% (NAV + dividendos)
- Dividend yield: 9.8% (distribuição trimestral)
- NAV appreciation: +4.4%
- Sharpe Ratio: 1.45

**Métricas de Risco:**
- Volatilidade anualizada: 12.8%
- Max drawdown (1Y): -6.2%
- CVaR 95%: -3.8%
- Beta vs S&P 500: 0.62

**Momentum:**
- RSI 14: 58.3 (neutro)
- Bollinger Position: 0.65 (terço superior)
- Blended Momentum Score: 62.5

**Fee Efficiency:**
- Expense ratio: 1.50%
- Fee drag ratio: 31.2%
- Fee efficiency score: 25.0/100 (acima da média para BDCs)

## Comparação com Pares

Comparado aos pares do segmento BDC (strategy_label: Private Credit):

| Métrica | ARCC | Mediana BDC | Percentil |
|---------|------|-------------|-----------|
| Dividend Yield | 9.8% | 10.5% | P45 |
| NAV Discount | -2.1% | -8.5% | P85 |
| Sharpe (1Y) | 1.45 | 0.92 | P82 |
| Net Operating Expenses | 1.50% | 2.15% | P78 |
| Non-Accrual Rate | 1.2% | 2.8% | P80 |

A ARCC destaca-se pela gestão de risco de crédito superior (non-accrual rate no quartil inferior) e pelo prêmio/desconto ao NAV mais favorável da categoria, refletindo a confiança do mercado na qualidade dos ativos.

## Perfil do Gestor (Ares Management)

**Ares Management Corporation** (NYSE: ARES) — gestora global de investimentos alternativos.

- **AUM Total:** $395B (Dez 2025)
- **Funcionários:** ~3,200 globalmente
- **Escritórios:** 35 cidades em 3 continentes
- **Divisão de Crédito:** $270B AUM — maior plataforma de direct lending dos EUA
- **Track Record:** 20+ anos em crédito privado, 15,000+ transações originadas
- **Compliance:** SEC registered (CRD: 152891), SOC2 Type II, UNPRI signatário

**Equipe de investimento da ARCC:**
- 180+ profissionais dedicados
- Experiência média: 18 anos em crédito
- Comitê de investimento: 8 membros senior
- Sourcing: ~$150B em deal flow anual, taxa de conversão <5%

## Análise de Holdings (N-PORT)

Baseado no último filing N-PORT (Q4 2025):

- **Total de holdings:** 487 posições
- **Top 10 concentração:** 18.5% do portfolio
- **Setor mais representado:** Software & Technology (22.3%)
- **Tipo de instrumento predominante:** First Lien Senior Secured (68.4%)
- **Floating rate:** 94.2% do portfolio (proteção natural contra alta de juros)
- **Maturidade média ponderada:** 4.2 anos
- **Spread médio:** SOFR + 585bps

## Recomendação

**MANTER** — ARCC é um holding core para exposição a crédito privado em portfólios institucionais. O premium ao NAV (+2.1% vs. peer average de -8.5%) é justificado pela escala da plataforma Ares, qualidade de underwriting superior (non-accrual 1.2%), e dividend yield competitivo. Monitorar: exposição concentrada a tecnologia (22.3%) e sensibilidade a ciclo de default em cenário de recessão."""
    else:
        title = "Manager Spotlight"
        subtitle = "Ares Capital Corporation (ARCC)"
        md = """\
## Fund Overview

**Ares Capital Corporation (ARCC)** is a Business Development Company (BDC) externally managed by Ares Management Corporation, one of the world's largest alternative credit managers with $395B in AUM (Dec 2025). ARCC is the largest publicly listed BDC in the US by total assets ($23.4B), focused on direct lending to US middle market companies.

**SEC Classification:** BDC (Business Development Company)
**Strategy Label:** Private Credit
**Expense Ratio:** 1.50% (net operating expenses)
**Management:** Externally managed by Ares Management (CRD: 152891)
**Investment Focus:** Senior secured, first lien — middle market ($50M-$250M EBITDA)

**Classification Flags:** Not an index fund, not a fund of funds, not target date.

## Quantitative Analysis

**Return Metrics (1Y):**
- Total return: +14.2% (NAV + dividends)
- Dividend yield: 9.8%
- Sharpe Ratio: 1.45

**Risk Metrics:**
- Annualized volatility: 12.8%
- Max drawdown (1Y): -6.2%
- CVaR 95%: -3.8%
- Beta vs S&P 500: 0.62

## Peer Comparison

Compared to BDC peers (strategy_label: Private Credit):

ARCC stands out with superior credit risk management (non-accrual rate in bottom quartile) and the most favorable NAV premium/discount, reflecting market confidence in asset quality.

## Manager Profile (Ares Management)

**Ares Management Corporation** (NYSE: ARES) — global alternative investment manager.
- **Total AUM:** $395B (Dec 2025)
- **Credit Division:** $270B AUM — largest US direct lending platform
- **Track Record:** 20+ years in private credit, 15,000+ transactions originated

## Recommendation

**HOLD** — ARCC is a core holding for private credit exposure. NAV premium justified by platform scale, superior underwriting quality, and competitive yield."""

    return title, subtitle, md


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview content PDFs")
    parser.add_argument("--language", choices=["pt", "en"], default="pt")
    args = parser.parse_args()
    lang: Language = args.language

    out_dir = Path(__file__).resolve().parent.parent / ".data"
    out_dir.mkdir(parents=True, exist_ok=True)

    generators = [
        ("long_form_report", _long_form_report_md),
        ("investment_outlook", _investment_outlook_md),
        ("macro_committee", _macro_committee_md),
        ("manager_spotlight", _manager_spotlight_md),
    ]

    for name, gen_fn in generators:
        title, subtitle, md = gen_fn(lang)
        pdf_buf = render_content_pdf(md, title=title, subtitle=subtitle, language=lang)
        out_path = out_dir / f"preview_{name}_{lang}.pdf"
        out_path.write_bytes(pdf_buf.read())
        print(f"  {name}: {out_path}")

    print(f"\nDone — {len(generators)} PDFs generated.")


if __name__ == "__main__":
    main()
