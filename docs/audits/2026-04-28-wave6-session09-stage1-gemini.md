# Wave 6 — Session 09 Stage 1 — Gemini 3.1 Pro Discovery Output

Date: 2026-04-28
Model: Gemini 3.1 Pro
Stage: 1 (parallel discovery, paired with Opus 4.6 output `2026-04-28-wave6-session09-stage1-opus.md`)
Scope: Wealth Routes & Workers Integration (per dispatch megaprompt `docs/prompts/2026-04-28-session-09-routes-workers-stage1-dispatch.md`)

---

## Auditor Findings

### ID: F-S09-001
**Title:** Update is_active to true on universe_sync upsert conflicts
**Files/lines:** `backend/app/domains/wealth/workers/universe_sync.py:219` + 296, 392, 465, 539
**Math severity:** N/A (Session 09 is integration, not math)
**Institutional severity:** Crit
**Type:** Race / Idempotency
**Evidence:**
```sql
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    attributes = instruments_universe.attributes || EXCLUDED.attributes,
    updated_at = now()
```
*(Missing `is_active = EXCLUDED.is_active` or `is_active = true`)*
**Expected invariant:** I-Reactivation-1
**Why it is wrong:** Quando a função `_deactivate_no_nav` detecta ausência de dados, ela corretamente define `is_active = false`. Porém, se os dados de NAV retornarem e o fundo for importado novamente (ex: via ESMA ou SEC), as 5 funções de upsert em `universe_sync.py` falham em reativá-lo, pois a cláusula `ON CONFLICT DO UPDATE` omite intencionalmente a atualização de `is_active`. O fundo permanece silenciado permanentemente e de forma arbitrária.
**Recommended fix:** Adicionar `is_active = EXCLUDED.is_active` a todas as 5 cláusulas `ON CONFLICT DO UPDATE SET` nos importadores dentro de `universe_sync.py`.
**Minimum test:** Inserir um fundo simulado, definir `is_active=False`. Executar `_sync_sec_etfs` com os mesmos dados de ticker do fundo e validar com um assert se `is_active == True`.
**Breaking-change risk:** None
**Confidence:** High
**Open questions:** N/A

---

### ID: F-S09-002
**Title:** Correct org_id type annotations to match UUID dependency
**Files/lines:** `backend/app/domains/wealth/routes/universe.py:155` + 325, 390, 482, 628 + 13 other route files (`model_portfolios.py`, `fact_sheets.py`, `dd_reports.py`, etc.)
**Math severity:** N/A
**Institutional severity:** Low
**Type:** Annotation
**Evidence:** `org_id: str = Depends(get_org_id)`
**Expected invariant:** I-Annotation-1
**Why it is wrong:** O injetor `get_org_id` retorna `uuid.UUID | None`, mas 13+ handlers anotam este parâmetro explicitamente como `str`. Apesar de o comportamento de execução estar funcionando por debaixo dos panos (já que `str`-specific methods não estão sendo usados nos corpos das rotas afetadas), isso é uma mentira de anotação que quebra as premissas de type checking e atua como uma armadilha fatal (footgun) para futuras refatorações.
**Recommended fix:** Modificar as assinaturas de todas as rotas afetadas de `org_id: str = Depends(get_org_id)` para `org_id: uuid.UUID | None = Depends(get_org_id)` (ou apenas `uuid.UUID` se obrigatório).
**Minimum test:** Realizar uma checagem de AST (`ast.parse`) assegurando que nenhum handler declare `org_id` como `str` se o default for `Depends(get_org_id)`.
**Breaking-change risk:** None
**Confidence:** High
**Open questions:** N/A

---

### ID: F-S09-003
**Title:** Flip prior screening results to is_current=False before insert
**Files/lines:** `backend/app/domains/wealth/routes/screener.py:837`
**Math severity:** N/A
**Institutional severity:** High
**Type:** Idempotency
**Evidence:** Lançamento de `IntegrityError: duplicate key value violates unique constraint` na restrição `uq_screening_results_current`.
**Expected invariant:** I-Idempotent-1
**Why it is wrong:** Durante reexecuções idênticas da rota de trigger do screener para o mesmo par `(organization_id, instrument_id)`, a aplicação tenta inserir um novo registro com `is_current=True`. Como ela falha em invalidar e marcar a linha idêntica do histórico prévio como `is_current=False`, colide com o partial-unique index resultando em uma falha de banco de dados irrecuperável que compromete a estabilidade da rota.
**Recommended fix:** Injetar uma instrução `update().where(ScreeningResult.organization_id == org_id, ScreeningResult.instrument_id == inst_id, ScreeningResult.is_current.is_(True)).values(is_current=False)` imediatamente antes do fluxo de `INSERT`.
**Minimum test:** Evocar `trigger_screening` duas vezes para o mesmo tenant e payload, atestando que a segunda chamada atualiza o registro com sucesso sem lançar nenhum `IntegrityError`.
**Breaking-change risk:** None
**Confidence:** High
**Open questions:** N/A

---

### ID: F-S09-004
**Title:** Enforce strict query parameters in catalog routes
**Files/lines:** `backend/app/domains/wealth/routes/screener.py:1894` + 2131, 2224
**Math severity:** N/A
**Institutional severity:** Med
**Type:** StrictParams
**Evidence:**
```python
async def get_catalog(
    q: str | None = Query(None, description="..."),
    ... > 10 other Query params
)
```
**Expected invariant:** I-Strict-Params-1
**Why it is wrong:** A API FastAPI injeta query parameters em handlers por argumento livre de função. Parâmetros não mapeados ou digitados com typo na URL pelo client (ex: `?text=Amundi`) não são rejeitados, mas sim completamente ignorados, devolvendo status 200 e tabelas massivas de >50k linhas não-filtradas. Essa tolerância silenciosa quebra o rigor institucional de integração de APIs.
**Recommended fix:** Mover todos os >5 filtros opcionais para um modelo Pydantic (`CatalogFilters`) que contenha `model_config = ConfigDict(extra="forbid")` e repassá-lo ao handler via `Depends()`.
**Minimum test:** Enviar um GET para `/catalog?unknown_param=123` e certificar-se de que a resposta resulta no status `422 Unprocessable Entity`.
**Breaking-change risk:** API contract (Qualquer client da API despachando query params incorretos no frontend começará a receber 422).
**Confidence:** High
**Open questions:** Devemos escalar o `extra="forbid"` globalmente como padrão Pydantic para todo o sistema da Wave 6 no futuro?

---

### ID: F-S09-005
**Title:** Wrap advisory lock unlocking in an immediate try/finally block
**Files/lines:** `backend/app/domains/wealth/workers/drift_check.py:36` (acquires lock) to 100 (unlocks)
**Math severity:** N/A
**Institutional severity:** Crit
**Type:** Lock
**Evidence:**
```python
lock_result = await db.execute(text(f"SELECT pg_try_advisory_lock({PIPELINE_LOCK_ID})"))
... no wrapping try ...
        try:
load config ...
        except Exception:
            config = None
        try:
check drift loop ...
        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({PIPELINE_LOCK_ID})"))
```
**Expected invariant:** I-Lock-1
**Why it is wrong:** A obtenção do lock `PIPELINE_LOCK_ID` não é imediatamente sucedida por um bloco `try/finally`. Se o worker de drift sofrer uma interrupção de sistema como `asyncio.CancelledError` ou `KeyboardInterrupt` durante as instâncias entre o lock e o primeiro catch — ou durante a própria busca inicial de configuração antes de entrar no segundo `try` — a execução encerra precocemente e nunca atinge o `finally`. O lock será "vazado", bloqueando toda a pipeline perpetuamente.
**Recommended fix:** Envolver todo o corpo de processamento após a aquisição positiva de `lock_result` em um único e master bloco `try...finally`.
**Minimum test:** Mockar o retorno de `VerticalConfigDefault.config` para invocar um erro de Cancelamento Assíncrono (`asyncio.CancelledError`) proposital. Executar o worker e verificar que `pg_advisory_unlock` foi chamado com sucesso sob qualquer circunstância adversa.
**Breaking-change risk:** None
**Confidence:** High
**Open questions:** N/A

---

## Checked Invariants With No Findings

- **I-Lock-2:** Todos os advisory locks ao longo do escopo de workers foram avaliados quanto a usos criminosos de `hash()`. Nenhum foi detectado; apenas literais ou métodos idôneos em queries brutas (como `hashtext()`) estão operando.
- **I-Idempotent-1 (siblings):** A busca por corrupção de status `is_current=True` no histórico de edições em `universe.py` (UniverseApproval) e `dd_reports.py` (DDReport) foi concluída. Ambos invertem de maneira robusta para `is_current=False` em inserções precedentes, ratificando a saúde das ramificações irmãs e isolando a falha à rota originária do `screener.py`.

## Top 3 Priorities

1. **F-S09-001 (Crit/Race):** Bug crítico na reativação do sincronizador global; impacta potencialmente milhares de fundos a ficarem "fantasmas" na infraestrutura, pois valid NAVs estão retornando sem ativarem fundos previamente silenciados.
2. **F-S09-005 (Crit/Lock):** Risco material de lock leak em `drift_check.py` paralisando irremediavelmente a pipeline inteira ao sofrer um CancelledError não-interceptado.
3. **F-S09-003 (High/Idempotency):** Quedas crônicas (`IntegrityError`) no `trigger_screening` reincidente que abatem a confiança no re-run determinístico.
