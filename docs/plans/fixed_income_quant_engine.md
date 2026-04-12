# Evolução do Quant Engine para Renda Fixa

Este plano descreve o design técnico para adicionar análises avançadas de Renda Fixa (Fixed Income) no Netz Analysis Engine. O foco é cobrir a deficiência do atual modelo focado em *Equities* extraindo as métricas principais: **Duration Empírica** (sensibilidade ao risco de juros) e **Beta de Crédito** (sensibilidade ao prêmio de risco/credit spread), fazendo regressões dos retornos do fundo contra benchmarks armazenados.

> [!IMPORTANT]
> **Aviso de Arquitetura (DB-First Pattern):** Como motores quantitativos não devem realizar chamadas de APIs externas na rota de execução, o modelo será integrado ao worker assíncrono noturno, conforme decisão do projeto.

## Decisão de Arquitetura Aprovada

A integração do motor de Renda Fixa ocorrerá via **Worker Noturno (`global_risk_metrics`)**:
- Centralizar o cálculo no worker (`global_risk_metrics`, Lock `900_071`) garante que as inferências complexas (regressões para calcular Duration e Beta) rodem apenas uma vez por dia por fundo ativo.
- As métricas calculadas serão persistidas diretamente na tabela global `fund_risk_metrics`.
- Quando o usuário visualizar o fundo, a leitura continuará muito rápida (O(1)), preservando a alta performance e tempo de resposta da API nas rotas `quant_analyzer.py`.

## Proposed Changes

---

### Quant Engine - Novo Serviço Analítico

A pasta `quant_engine` contém serviços matemáticos independentes do vertical.

#### [NEW] `backend/quant_engine/fixed_income_analytics_service.py`
Novo módulo projetado com bibliotecas científicas (NumPy / SciPy) para calcular estatísticas de Renda Fixa baseando-se em séries temporais (Return-Based Style Analysis).
- **Funções Previstas:**
  - `compute_empirical_duration(fund_returns: np.ndarray, treasury_yield_changes: np.ndarray, config: dict) -> float`
  - `compute_credit_beta(fund_returns: np.ndarray, credit_spread_changes: np.ndarray, config: dict) -> float`
  - Métodos utilitários para alinhar datas dos retornos de NAV com os *timestamps* do TimescaleDB extraídos pela `macro_data`.

---

### Ingestão & Risk Metrics Worker

A lógica do serviço matemático será acoplada ao pipeline preexistente, processando essas regressões antes de salvar os registros de risco daquele dia.

#### [MODIFY] Worker `global_risk_metrics` (Lock 900_071)
- Acionar os métodos `compute_empirical_duration` e `compute_credit_beta` durante o loop de cômputo diário.
- Consultar a base `macro_data` via SQL para trazer as curvas de Yield em janela móvel e injetar os dados no motor matemático recém-criado.
- Requerer a criação de instâncias numéricas persistentes no modelo e no banco para comportar os novos dados (Ex: Update da Model SQLAlchemy `FundRiskMetrics` seguida de um `make migration MSG="add_fixed_income_risk_metrics"` para persistir colunas referentes ao empirical duration e credit_beta).

## Verification Plan

### Automated Tests
- Criar bloco forte de testes em `backend/tests/quant_engine/test_fixed_income_analytics_service.py` injetando vetores simulados contendo fundos puramente de renda fixa x equities puras (dummy data), validando sinal (beta positivo/negativo e rádio coerente).
- Testar Worker certicando de que os cálculos de DataFrames não rodam sobre o event_loop assíncrono em `global_risk_metrics` sem usar blocos de `run_in_executor/to_thread()` adequadamente para não travar conexões ativas.
- Garantir sucesso integral em `make check`.
