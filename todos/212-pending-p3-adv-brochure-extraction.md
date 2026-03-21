---
status: done
priority: p3
issue_id: "212"
tags: [backend, data-provider, sec, adv, ocr]
dependencies: []
---

# ADV Part 2A brochure extraction via Mistral OCR (Phase 5)

## Problem Statement

`AdvService.fetch_manager_team()` is currently a stub returning `[]`. Full implementation requires downloading ADV Part 2A brochures from SEC EDGAR, extracting text via Mistral OCR, and storing for full-text search across manager philosophies.

## Proposed Solution

### Approach

1. **Implement `fetch_manager_team()`** in `backend/data_providers/sec/adv_service.py`:
   - Download ADV Part 2A PDF from SEC EDGAR
   - Extract text via Mistral OCR (existing pipeline in `ai_engine/extraction/`)
   - Parse team members (name, title, certifications, experience, bio)
   - Store in `sec_manager_team` (existing table)

2. **New table `sec_manager_brochure_text`:**
   - `crd_number TEXT NOT NULL`
   - `section TEXT NOT NULL` (e.g., "investment_philosophy", "risk_management")
   - `content TEXT NOT NULL`
   - `filing_date DATE NOT NULL`
   - `created_at TIMESTAMPTZ`
   - Primary key: `(crd_number, section, filing_date)`

3. **Enable search** like "find all managers mentioning 'ESG integration'" via `tsvector` full-text index on `content` column.

4. **Migration** for `sec_manager_brochure_text` table + GIN index on `tsvector`.

## Technical Details

**Affected files:**
- `backend/data_providers/sec/adv_service.py` — implement `fetch_manager_team()` stub
- New migration for `sec_manager_brochure_text` table
- `backend/app/shared/models.py` — add `SecManagerBrochureText` model

**Constraints:**
- Uses Mistral OCR (existing, `MISTRAL_API_KEY` env var)
- ADV Part 2A PDFs can be 50+ pages — Mistral handles via existing pipeline
- Global table (no RLS)
- SEC EDGAR rate limit: 8 req/s

## Acceptance Criteria

- [ ] `fetch_manager_team()` returns actual team data instead of `[]`
- [ ] Brochure text stored with section classification
- [ ] Full-text search works via `tsvector` index
- [ ] Migration creates table + GIN index
- [ ] `make check` passes (lint + typecheck + test)


# Correção: todo #212 — substituir Mistral OCR por PyMuPDF em adv_service.py

## Contexto

O todo #212 foi implementado com Mistral OCR para extrair texto dos brochures ADV Part 2A.
Isso está errado por um fato descoberto após a implementação:

**O SEC exige por regulação (desde 2010) que todos os brochures ADV Part 2A sejam
submetidos ao sistema IARD como PDF text-searchable.** Arquivos escaneados sem texto
extraível são rejeitados na submissão. Portanto, todos os brochures disponíveis via
`reports.adviserinfo.sec.gov` já contêm texto extraível diretamente — OCR é desnecessário.

PyMuPDF (`fitz`) já é dependência do projeto (usado em `ai_engine/pipeline/unified_pipeline.py`).
Custo: zero. Latência: milissegundos vs 10-30s do Mistral. Sem API key necessária.

## O que mudar

### 1. `backend/data_providers/sec/adv_service.py`

Localizar a função `_download_and_ocr_brochure()` e substituí-la por
`_download_and_extract_brochure()` que usa PyMuPDF:
```python
def _download_and_extract_brochure(crd_number: str) -> str:
    """Download ADV Part 2A PDF and extract text via PyMuPDF.

    SEC requires all Part 2A brochures to be text-searchable PDF before
    IARD submission (mandatory since 2010). OCR is therefore not needed.
    Uses fitz (pymupdf) — zero API cost, millisecond latency.

    Returns concatenated page text or empty string on failure.
    Runs in SEC thread pool (sync).
    """
    import fitz  # pymupdf — already a project dependency
    import httpx

    pdf_url = _ADV_BROCHURE_URL.format(crd=crd_number)
    check_iapd_rate()

    try:
        resp = httpx.get(
            pdf_url,
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=60.0,
            follow_redirects=True,
        )
        if resp.status_code == 404:
            logger.info("adv_brochure_not_found", crd=crd_number)
            return ""
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("adv_brochure_download_failed", crd=crd_number, error=str(exc))
        return ""

    pdf_bytes = resp.content
    if len(pdf_bytes) < 1024:
        logger.warning("adv_brochure_too_small", crd=crd_number, size=len(pdf_bytes))
        return ""

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            pages = [page.get_text("text") for page in doc]
        text = "\n\n".join(p for p in pages if p.strip())
        logger.info(
            "adv_brochure_extracted",
            crd=crd_number,
            pages=len(pages),
            chars=len(text),
        )
        return text
    except Exception as exc:
        logger.warning("adv_brochure_extract_failed", crd=crd_number, error=str(exc))
        return ""
```

Atualizar todos os call sites de `_download_and_ocr_brochure(crd_number)` para
`_download_and_extract_brochure(crd_number)`.

Remover do arquivo:
- Constantes `MISTRAL_*` (MISTRAL_OCR_URL, MISTRAL_MODEL, etc.)
- Import `base64` se usado apenas para o OCR payload
- Qualquer referência à Mistral API key (`settings.MISTRAL_API_KEY`) dentro de adv_service.py

Atualizar o docstring do módulo no topo do arquivo — remover menção a "OCR via Mistral".

### 2. `backend/data_providers/sec/adv_service.py` — docstring da classe `AdvService`

Atualizar para remover referência a Mistral OCR. Substituir por:
"Team bios come from Part 2A PDF brochures (text extraction via PyMuPDF)."

### 3. Testes — `backend/tests/test_data_providers_adv.py`

Remover ou adaptar qualquer teste que mocke a chamada à Mistral API.
Os testes de `_classify_brochure_sections()` e `_parse_team_from_brochure()` não
precisam mudar — recebem texto como input, não se importam com a origem.
Adicionar 1 teste para `_download_and_extract_brochure()` mockando `httpx.get`
para retornar PDF bytes mínimos válidos e verificar que `fitz.open` é chamado
(ou simplesmente verificar que retorna string não-vazia com um PDF real de teste).

## O que NÃO mudar

- Migration `0041_sec_manager_brochure_text.py` — tabela e GIN index corretos, não tocar
- `SecManagerBrochureText` ORM model em `shared/models.py` — correto, não tocar
- `AdvBrochureSection` dataclass em `models.py` — correto, não tocar
- `_classify_brochure_sections()` — correto, não tocar
- `_parse_team_from_brochure()` — correto, não tocar
- `_upsert_team()` / `_upsert_brochure_sections()` — corretos, não tocar
- `search_brochure_text()` — correto, não tocar
- `pyproject.toml` — contrato import-linter `data_providers` não pode importar `ai_engine`
  está correto e deve ser mantido
- `fetch_manager_team()` e `extract_brochure()` — lógica correta, apenas atualizar
  o call site interno de `_download_and_ocr` para `_download_and_extract`

## Verificação

Após a mudança:
- `grep -r "MISTRAL" backend/data_providers/` deve retornar zero resultados
- `grep -r "mistral" backend/data_providers/` deve retornar zero resultados
- `make check` deve passar (lint + typecheck + 51 testes ADV)
- `python -c "from data_providers.sec.adv_service import AdvService; print('ok')"` deve funcionar
