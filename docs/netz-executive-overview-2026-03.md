# Netz Analysis Engine
## Visão Executiva — Março 2026

---

# O Problema que Resolvemos

Gestores institucionais tomam decisões de alocação e due diligence com dados
fragmentados entre múltiplas fontes, planilhas manuais e relatórios desatualizados.
O processo de avaliação de um único fundo — da triagem inicial ao memo para o
comitê de investimentos — consome semanas e depende de analistas sênior para
tarefas repetitivas de coleta e formatação de dados.

O Netz Analysis Engine é um sistema operacional institucional que integra dados
regulatórios, quantitativos e documentais em um único ambiente, acelerando o ciclo
completo de análise sem comprometer o rigor metodológico.

---

# O que o Sistema Faz

O sistema cobre o ciclo completo de decisão de investimento em duas verticais.

## Vertical Wealth — Gestão de Portfólios

**1. Inteligência Macroeconômica**
Monitoramento contínuo de 78 séries do Federal Reserve, 278 séries do Tesouro
americano, dados do BIS (43 países) e projeções do FMI (44 países, até 2030).
O sistema classifica automaticamente o regime de mercado — Normal, Defensivo,
Inflacionário ou Crise — com base em múltiplos indicadores de mercado e economia
real. Relatórios semanais de comitê são gerados automaticamente com detecção de
mudanças materiais por região.

**2. Alocação e Otimização de Portfólios**
Avaliação diária de risco por perfil de portfólio com limites configuráveis por
mandato. Otimização de carteira com suporte a objetivo único (máximo retorno
ajustado ao risco) e multiobjetivo (fronteira eficiente de risco vs retorno).
Monitoramento contínuo de violações de limite com rastreamento de dias
consecutivos e alertas automáticos.

**3. Triagem de Fundos**
Pipeline determinístico de três camadas: filtros eliminatórios (restrições hard de
mandato), adequação ao mandato (com margem de watchlist), e ranking quantitativo
por score composto auditável. Aplicado simultaneamente a fundos americanos
(976.980 gestores no registro SEC) e europeus (10.436 fundos UCITS no registro ESMA).

**4. Due Diligence**
Geração automatizada de relatórios de due diligence com 8 capítulos estruturados:
sumário executivo, estratégia de investimento, avaliação do gestor, análise de
performance, framework de risco, análise de taxas, due diligence operacional e
recomendação. Cada relatório integra dados quantitativos de risco, dados
regulatórios da SEC (Form ADV, 13F), e o texto real dos documentos depositados
pelo gestor junto ao regulador americano. Score de confiança determinístico e
âncora de decisão (APROVAR / CONDICIONAL / REJEITAR) para o comitê.

**5. Comitê de Investimentos**
Fluxo estruturado de aprovação com bloqueio de auto-aprovação, versionamento de
relatórios e rastreabilidade completa de decisões. O analista vai da triagem ao
memo de IC sem sair do sistema.

**6. Gestão de Portfólios Modelo**
Construção e acompanhamento de portfólios modelo com alocação estratégica por
perfil (conservador, moderado, crescimento). Análise de atribuição de performance
(decomposição Brinson-Fachler com linking multiperiodo). Monitoramento de drift
estratégico com detecção de mudança de estilo via séries temporais.

**7. Rebalanceamento**
Engine de rebalanceamento com proposta automática de pesos, análise de impacto
de turnover, e estados de aprovação rastreáveis. Acionado por violações de limite
de risco, mudanças de regime ou calendário definido pelo gestor.

## Vertical Credit — Private Credit Underwriting

**Dataroom e Processamento de Documentos**
Pipeline de ingestão de documentos com OCR, classificação automática (31 tipos
canônicos de documentos), chunking semântico e indexação vetorial. Suporte a
CIMs, term sheets, demonstrações financeiras, documentos legais e materiais de
sponsor. Os documentos são a base de evidência para os memos de IC.

**Deep Review — Memo para Comitê de Investimentos**
Geração de memos de IC com 13 estágios de análise e 14 capítulos estruturados.
O sistema diferencia sinais HIGH, MODERATE e AMBIGUOUS por capítulo, expandindo
a busca de evidências automaticamente onde a confiança é menor. Reranking local
de evidências para máxima relevância sem dependência de APIs externas de ML.
Score de sinal determinístico e revisão adversarial integrada.

---

# A Base de Dados

O sistema agrega dados de sete fontes primárias em tempo real ou com ingestão
automatizada.

**Gestores de Investimento Americanos (SEC)**
976.980 gestores do registro FOIA da SEC, incluindo 15.963 Registered Investment
Advisers com AUM combinado superior a US$ 38 trilhões. Dados incluem AUM
histórico, estrutura de taxas, equipe de gestão, histórico de compliance e
documentos regulatórios completos (Form ADV Part 2A). Os 10 maiores gestores
incluem Vanguard (US$ 7,9T), Fidelity (US$ 3,96T) e BlackRock (US$ 3,05T).

**Holdings Institucionais Americanos (13F)**
1,09 milhão de posições de 12 grandes investidores institucionais com histórico
de 25 anos (2000-2025). Inclui Norges Bank (fundo soberano norueguês), Northern
Trust, Invesco, Franklin Templeton e Two Sigma, entre outros. Cobre mais de
US$ 8,9 trilhões em AUM no trimestre mais recente. Análise de drift de portfólio
trimestre a trimestre com classificação de posições novas, aumentadas, reduzidas
e encerradas.

**Fundos UCITS Europeus (ESMA)**
10.436 fundos UCITS de 658 gestores registrados no ESMA, cobrindo 25 países com
predominância em Luxemburgo (81,8%) e França (6,2%). Principais gestores incluem
Amundi (427 fundos), UBS (309) e DWS (295). Linkage de 100% entre fundos e
gestores. Resolução de ticker Yahoo Finance em andamento para séries históricas
de NAV.

**Dados Macroeconômicos (FRED / Tesouro / BIS / IMF / OFR)**
78 séries do Federal Reserve cobrindo taxas de juros, spreads de crédito, mercado
imobiliário (20 metros Case-Shiller), emprego, inflação e sentimento do consumidor.
278 séries do Tesouro americano. Indicadores de estabilidade financeira do BIS
(43 países) e projeções macroeconômicas do FMI (44 países, horizonte até 2030).
Dados semanais do OFR sobre a indústria de hedge funds — tamanho, alavancagem
por estratégia e cenários de stress.

**Holdings de Fundos Registrados (N-PORT)**
132.823 posições de 69 companhias de investimento registradas, com predominância
em fundos municipais americanos (T. Rowe Price, Morgan Stanley, Franklin Templeton,
Fidelity). Dados mensais a partir de 2019.

---

# Metodologia e Auditabilidade

O sistema foi projetado para uso institucional com rastreabilidade completa de
cada cálculo. Todos os métodos quantitativos são baseados em literatura acadêmica
e prática de mercado estabelecida.

**Métricas de risco** calculadas internamente a partir de dados históricos: CVaR
histórico, VaR, Sharpe, Sortino, máximo drawdown, alpha, beta, information ratio
e tracking error — sem dependência de provedores externos de dados de risco.

**Detecção de drift estratégico** via Dynamic Time Warping derivativo (dDTW),
comparando a série de retornos de cada fundo contra o benchmark do seu bloco de
alocação. Complementado por análise de z-score em 7 métricas de risco com janelas
de baseline de 12 meses.

**Correlação e diversificação** com denoising de Random Matrix Theory
(Marchenko-Pastur), estimativa de covariância com encolhimento Ledoit-Wolf,
Absorption Ratio (Kritzman & Li, 2010) e Diversification Ratio (Choueifaty).

**Atribuição de performance** por decomposição Brinson-Fachler com ajuste Fachler
(eliminação de viés de alocação) e linking multiperiodo pelo método Carino.

**Due diligence** com scoring determinístico de confiança (0-100) baseado em
completeness de evidência, cobertura quantitativa e resultado de revisão
adversarial. Decisão de comitê (APROVAR / CONDICIONAL / REJEITAR) derivada do
score e do conteúdo do capítulo de recomendação.

---

# Arquitetura e Infraestrutura

**Multi-tenant por design.** Cada organização opera em isolamento completo de
dados — sem possibilidade de um tenant acessar dados de outro. Dados regulatórios
globais (SEC, ESMA, macro) são compartilhados entre tenants; dados de portfólio,
instrumentos e relatórios são estritamente segregados por organização.

**Dados externos nunca chamados durante requests de usuário.** Toda a ingestão
de dados externos (Yahoo Finance, FRED, SEC EDGAR, ESMA, Tesouro, BIS, IMF, OFR)
é feita por workers de background com agendamento, idempotência e bloqueio
coordenado. As interfaces do usuário leem exclusivamente do banco de dados
local — zero latência de APIs externas no caminho crítico.

**Série temporal nativa.** Dados históricos armazenados em banco de dados
TimescaleDB com compressão automática, índices otimizados e agregações
pré-computadas. Queries de analytics sobre anos de histórico diário executam
em milissegundos.

**Infraestrutura de custo controlado.** Arquitetura projetada para até 50 tenants
institucionais com custo de infraestrutura entre US$ 100-200/mês. Componentes:
banco de dados Timescale Cloud, Railway (API), Upstash Redis, Cloudflare R2
(storage de documentos).

---

# Estado Atual do Sistema

O sistema está em produção com os seguintes dados confirmados em base de dados:

| Fonte | Volume |
|---|---|
| Gestores SEC (FOIA) | 976.980 entidades |
| Registered Investment Advisers | 15.963 |
| AUM combinado (RIAs) | > US$ 38 trilhões |
| Holdings institucionais (13F) | 1.092.225 posições / 25 anos |
| Diffs de portfólio trimestre a trimestre | 1.071.320 |
| Fundos UCITS (ESMA) | 10.436 |
| Gestores ESMA | 658 |
| Documentos ADV Part 2A (seções) | 17.837 seções / 2.157 gestores |
| Holdings de fundos registrados (N-PORT) | 132.823 posições |
| Séries macroeconômicas | 78 FRED + 278 Tesouro + 23 OFR |
| Países cobertos (BIS/IMF) | 43-44 países |
| Benchmark ETFs (NAV diário) | 16 blocos de alocação |

---

# Próximos Passos

Com a base de dados e o motor analítico operacionais, os próximos marcos de
desenvolvimento são:

**Cobertura de fundos UCITS.** Expansão da resolução de tickers Yahoo Finance
para os 7.507 fundos europeus ainda sem cotação, e integração futura com
provedores de dados como FE fundinfo para histórico completo de NAV de fundos
domiciliados na Europa.

**Unificação do modelo de instrumento.** Consolidação do pipeline de workers de
risco e portfólio para operar sobre um único modelo de instrumento, eliminando
redundância de dados interna.

**Atribuição a partir de dados pré-agregados.** Migração das queries de
atribuição de performance para leitura a partir de retornos mensais pré-computados,
reduzindo latência dos endpoints analíticos mais pesados.

**Expansão do vertical Credit.** Memos de IC com cobertura EDGAR expandida
(10-K, proxy statements) e integração de dados de sponsor via SEC.

---

Documento preparado pela equipe Netz — Março 2026.
Confidencial. Para uso exclusivo dos sócios.
