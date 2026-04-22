---
title: feat: Command Palette Architecture Design
type: feat
status: active
date: 2026-04-21
origin: prompt
deepened: 2026-04-21
---

# feat: Command Palette Architecture Design

## Overview

Implementação do plano arquitetural para a Command Palette (Cmd+K) do Netz Terminal. A ferramenta seguirá o padrão "Superhuman/Raycast", focando em extrema velocidade, mesclando atalhos estáticos locais, ações contextuais e busca assíncrona de fundos via API. O objetivo desta especificação é definir contratos de interface, gerenciamento de estado e estratégia de busca de baixa latência sem escrever código funcional final.

## Problem Frame

O invólucro visual (Shell) do Netz Terminal já existe e intercepta o atalho Cmd+K, mas carece de conteúdo e roteamento lógicos. O desafio principal é realizar buscas assíncronas no universo de ativos (`mv_unified_funds`) com latência < 50ms, mesclando essas opções com atalhos locais de forma instantânea, e sem causar re-renders desnecessários no App Shell ao abrir/fechar a paleta. A experiência deve ser 100% controlável via teclado.

## Requirements Trace

- **R1.** Busca de Fundos (texto/ticker) consumindo a materialized view `mv_unified_funds` via FastAPI.
- **R2.** Suporte a Atalhos de Navegação (/screener, /allocation, /live) e Ações Contextuais ("Importar Fundo").
- **R3.** Latência < 50ms na busca assíncrona (exigindo estratégias de caching e debounce).
- **R4.** Gerenciamento de estado otimizado usando Runes do Svelte 5, evitando propagação de renders pelo App Shell.
- **R5.** Navegação restrita por teclado (Setas, Enter, Escape) com a11y adequado (ARIA).

## Scope Boundaries

- **Out of scope:** Modificar a estrutura da materialized view `mv_unified_funds` (operação estritamente read-only).
- **Out of scope:** Integrar funcionalidades de RAG ou IA gerativa (busca puramente textual/semântica).
- **Out of scope:** Utilizar bibliotecas de command palette de terceiros (o layout visual já utiliza `@netz/ui`).
- **Out of scope:** Implementação funcional de SvelteKit ou FastAPI (esta é uma etapa de design e definição de interfaces).

## Context & Research

### Relevant Code and Patterns
- O pacote `@netz/ui` já fornece os design tokens e layouts base.
- O App Shell atual intercepta os comandos de teclado; precisamos conectar isso a um store reativo isolado.
- Backend FastAPI possui acesso à `mv_unified_funds` e utiliza Pydantic `response_model` para as respostas.

## Key Technical Decisions

- **Busca Híbrida (Local + Async):** A paleta irá mesclar resultados estáticos instantâneos com resultados da API de forma assíncrona usando uma runa `$derived` para combinar os arrays.
- **Store Svelte 5 Isolada:** O estado da paleta (visibilidade, query, seleção) viverá em um módulo `.svelte.ts` fora do componente para não disparar re-renders no Shell global.
- **Backend Caching & Single-Flight:** A rota de busca fará cache no Redis (Upstash) por 5-15 minutos e aplicará headers de `Cache-Control`.
- **Interface Base Polimórfica:** `CommandItem` será a base para `FundResult`, `RouteShortcut` e `ActionCommand`.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

**1. Assinatura da API de Busca (FastAPI / Pydantic)**

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class FundSearchResult(BaseModel):
    instrument_id: str = Field(..., description="UUID do fundo")
    name: str = Field(..., description="Nome do fundo")
    ticker: Optional[str] = Field(None, description="Ticker, se aplicável")
    strategy_label: Optional[str] = Field(None, description="Classificação da estratégia")
    asset_class: Optional[str] = Field(None, description="Classe de ativo")

class SearchResponse(BaseModel):
    results: List[FundSearchResult]
    latency_ms: float
```
*(A query rodará via ILIKE ou pg_trgm em `mv_unified_funds`, restrita ao tenant/global).*

**2. Tipologia de Comandos (Svelte / TypeScript)**

```typescript
export type CommandType = 'fund' | 'route' | 'action';

export interface CommandItem {
    id: string;
    type: CommandType;
    title: string;
    subtitle?: string;
    icon?: string;
    onSelect: () => void;
}

export interface FundResult extends CommandItem {
    type: 'fund';
    instrument_id: string;
    strategy_label?: string;
}

export interface RouteShortcut extends CommandItem {
    type: 'route';
    path: string;
}

export interface ActionCommand extends CommandItem {
    type: 'action';
    event_id?: string;
}
```

## Implementation Units

- [ ] **Unit 1: Backend Search API Specification**
**Goal:** Estabelecer a rota de busca `/search` consumindo `mv_unified_funds`.
**Requirements:** R1, R3
**Dependencies:** None
**Files:**
- Modify: `backend/app/domains/wealth/routes/search.py` (ou similar)
**Approach:** 
- Rota deve aceitar `q` (query) e `limit` (max 20).
- Aplicar cache no Redis via `ConfigService` / Upstash para as queries, TTL 5-15 min.
- Headers `Cache-Control: private, max-age=300, stale-while-revalidate=60`.
**Test scenarios:**
- Edge case: Input menor que 2 caracteres retorna bad request ou lista vazia rápido.
- Happy path: Busca retorna objetos formatados seguindo `SearchResponse` model em < 50ms para fundos existentes.

- [ ] **Unit 2: Svelte 5 Global State Management**
**Goal:** Criar a store encapsulada para evitar re-renders globais.
**Requirements:** R4
**Dependencies:** None
**Files:**
- Create: `frontends/terminal/src/lib/stores/palette.svelte.ts`
**Approach:**
- Usar runa `$state` exportando objeto com `isOpen`, `query`, `selectedIndex`, `results`.
- Criar funções utilitárias `togglePalette(force?: boolean)` para controle externo.
**Test scenarios:**
- Happy path: Chamar `togglePalette()` inverte o valor de `isOpen` e reseta o `query` quando fechado.

- [ ] **Unit 3: Command Palette Core & Data Merge**
**Goal:** O componente visual que reage à digitação e unifica comandos locais e resultados async.
**Requirements:** R1, R2, R4
**Dependencies:** Unit 1, Unit 2
**Files:**
- Modify: `frontends/terminal/src/lib/components/CommandPalette.svelte`
**Approach:**
- `query` ativa um debounce (150-250ms) antes do fetch pro backend.
- Um bloco `$derived` mescla os atalhos locais filtrados sincronamente (ex: `/screener`) com os resultados do fetch em uma lista tipada como `CommandItem[]`.
**Test scenarios:**
- Happy path: Digitar "scre" exibe a rota /screener imediatamente (local), depois popula fundos com "scre" após a requisição async completar.

- [ ] **Unit 4: Strict-Keyboard Navigation & A11y**
**Goal:** Garantir navegação rápida por teclado e padrões ARIA.
**Requirements:** R5
**Dependencies:** Unit 3
**Files:**
- Modify: `frontends/terminal/src/lib/components/CommandPalette.svelte`
- Modify: App Shell `+layout.svelte` para bindar `<svelte:window onkeydown={...}>` (se não existir).
**Approach:**
- Lidar com setas via modificação de `selectedIndex`.
- Rolagem automática usando `$effect` com `element.scrollIntoView({ block: 'nearest' })`.
- Focus trap no input raiz ao abrir. Attributes: `role="combobox"`, `role="listbox"`, `aria-activedescendant`.
**Test scenarios:**
- Edge case: Apertar ArrowUp no index 0 vai pro final da lista (ou é ignorado/bloqueado).
- Happy path: Apertar Enter dispara a função `onSelect` e invoca `togglePalette(false)`.

## System-Wide Impact

- **Interaction graph:** O componente App Shell agora precisa interceptar Cmd+K (se já não o fizer adequadamente) de forma puramente delegativa para a store da paleta.
- **Performance:** Uma implementação correta do store isolado Svelte 5 assegurará zero frame-drops no restante do layout.
- **Backend Load:** Se não configurarmos o Cache corretamente e houver muitas sessões simultâneas, o `ILIKE` na `mv_unified_funds` pode elevar o IO do TimescaleDB no hot path. Daí a obrigatoriedade de Redis.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Custo computacional O(N) do texto na view | Limitar tamanho da query, requerimento de min-length, e cache forçado de Redis + Http Header. |
| Re-render excessivo travando digitação | Estado do form será restrito ao módulo `.svelte.ts` + `<CommandPalette>` individual. |
| Race condition no fetch da API de busca | Utilizar classe AbortController dentro do bloco de trigger debounceado. |

## Sources & References

- **Origin document:** Solicitação original da Command Palette.
- Código de Svelte 5 runes (`$state`, `$derived`, `$effect`).
- GEMINI.md (Smart Backend, Dumb Frontend; Async-first route policies).
