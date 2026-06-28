# Plano: promessas da landing vs produto real

> Documento de referência para alinhar marketing (landing) e produto interno.  
> Última atualização: 2026-06-26 · **Fase 0 em execução**

## Resumo executivo

A landing descreve um **sistema fechado de elite** (biometria → treino adaptado → log → review → mesociclo → nutrição sincronizada). O código entrega um **MVP forte em treino adaptativo + programação AI**, com recovery manual e integrações pontuais.

**Maiores buracos de credibilidade:**

1. **Auto meal planning** — prometido em hero, features, pricing; quase nada no backend.
2. **Apple Health na web** — trust strip sugere sync transparente; na prática é app iOS companion ou check-in manual.
3. **Loop automático** — reviews dominicais e apply da próxima semana exigem ações do usuário ou cron ops.
4. **Analytics / PRs automáticos** — marketing afirma; produto exige entrada manual.
5. **"Training Only"** — salva preferência no DB mas não esconde nutrição na UI.

---

## Matriz promessa → status

| Promessa | Status | Evidência |
|----------|--------|-----------|
| Treino adaptativo ao recovery | **Implementado** | `adaptive.py`, `readiness.py`, `/api/v1/training/today` |
| Smart programming (HWPO/Mayhem/etc.) | **Parcial** | cfai + `programs.py`; onboarding não escolhe metodologia |
| Weekly reviews estilo coach | **Parcial** | `weekly_reviewer.py`; geração/apply manual; cron externo |
| Auto meal planning | **Stub** | Log + targets; `today.py` fueling `mock: true` |
| Recovery 20s ou Apple Health | **Parcial** | API recovery; HealthKit iOS-only |
| Apple Health / Watch (trust) | **Parcial** | `healthkit.py` + `ios/`; web = docs |
| Lab OCR | **Implementado** | `ocr.py` + `health.html` |
| Google Calendar | **Parcial** | OAuth + sync treinos 7d; sem refeições |
| Analytics / PRs automáticos | **Parcial** | PR manual; sem relatório mensal |
| Trial 14d sem cartão | **Implementado** | `auth.py` |
| Stripe $29/mo | **Parcial** | `billing.py`; precisa env em prod |
| Training Only esconde nutrição | **Não funciona** | `nutrition_enabled` no DB; nav sempre visível |
| Export pós-cancelamento | **Não construído** | FAQ promete 30 dias |

---

## Apple Health — detalhe

```
iPhone (app SwiftUI) → POST /api/v1/integrations/healthkit/sync
                              ↓
                    healthkit.py → recovery_metrics + readiness
                              ↓
                    adaptive engine
```

- **Web/PWA:** sem sync; guia em `/dashboard/integrations` (autenticado) e `/help#healthkit`.
- **Dashboard:** não mostra origem dos dados (Manual vs HealthKit).

---

## Demo "Como funciona" vs UI interna

| Painel | Promessa visual | UI real | Gap |
|--------|-----------------|---------|-----|
| s1 Check-in | HRV + sono + "Apple Health" | Modal reduzido no dashboard | Sem badge sync |
| s2 Treino | Volume ×1.0, "Adapted" | Card sem multiplicador | API tem dados; UI ignora |
| s3 Log | Série a série + RPE | Modal training.html | UX diferente |
| s4 Review | Barras + próximo foco | Texto + Apply manual | Não automático |
| s5 Mesociclo | Timeline de fases | schedule/programs | Cold start; não no dashboard |

---

## Plano de fases

### Fase 0 — Honestidade imediata ✅ (esta entrega)

| # | Ação |
|---|------|
| 0.1 | Trust strip: Apple Health/Watch → via app iOS |
| 0.2 | Tile nutrição → tracking de macros (não "auto meal planning") |
| 0.3 | Pricing feat4 → meal & macro tracking |
| 0.4 | FAQ a5 → Training Only honesto (preferência salva; UI em Fase 1) |
| 0.5 | FAQ a7 → Menu → Billing; export em breve |
| 0.6 | Hero eyebrow → link #requirements |
| 0.7 | Demo s1 → check-in manual ou app iOS |
| 0.8 | Seção "O que você precisa" na landing |

**Extras nesta entrega:** recovery, weekly, analytics e feat6/pricing alinhados ao que existe hoje.

### Fase 1 — UI interna alinhada (1–2 semanas)

- 1.1 Gating `nutrition_enabled` na navbar
- 1.2 Dashboard: card readiness (HRV, sono, badge Manual/HealthKit)
- 1.3 Dashboard: `volume_multiplier` + `recommendation` no treino de hoje
- 1.4 Check-in rápido 4 campos no dashboard
- 1.5 Reviews: barras visuais + CTA Apply inline
- 1.6 Widget mesociclo no dashboard
- 1.7 Integrations: status último sync HealthKit
- 1.8 Onboarding: "Generate my first week"
- 1.9 Demo landing ↔ labels do dashboard

### Fase 2 — Gaps médios (2–4 semanas)

- Review automático + notificação
- Apply review com confirmação única
- Metodologias no onboarding
- Export LGPD
- GCal auto-sync + timezone usuário
- Stripe em prod
- PR detection pós-sessão
- iOS app visível pós-signup (TestFlight)

### Fase 3 — Build real ou remover do marketing

- Auto meal planning (regras mínimas) **ou** remover promessa
- Analytics mensal **ou** remover
- Plan fit score **ou** remover widget demo
- Web Apple Health via Health Auto Export **ou** manter só iOS
- `today.py` fueling real (remover `mock: true`)

### Fase 4 — Contínuo

- Matriz promessa→status no `ROADMAP.md`; CI de consistência copy/código
- Componentes demo reutilizados no dashboard
- E2E Playwright do loop completo

---

## Priorização recomendada

```
Agora          → Fase 0 ✅
Próximas 2 sem → Fase 1.1–1.8 + Stripe + iOS visível
Decisão        → Fase 3.1 meal planning: construir OU remover
Não prometer   → analytics mensal, plan fit score, auto-apply review
```

---

## Referências no código

| Área | Caminho |
|------|---------|
| Landing copy | `backend/app/i18n/{en,pt-BR}.json` → `landing` |
| HealthKit | `backend/app/core/integrations/healthkit.py`, `ios/` |
| Adaptativo | `backend/app/core/engine/adaptive.py`, `readiness.py` |
| Reviews | `backend/app/core/engine/weekly_reviewer.py`, `reviews.html` |
| Nutrição | `nutrition.html`, `today.py` (mocks) |
| OCR | `backend/app/core/integrations/ocr.py` |
| Calendar | `backend/app/core/integrations/calendar.py` |
| Onboarding | `onboarding.html`, `onboarding.py` |
| Billing | `billing.py`, `billing.html` |
