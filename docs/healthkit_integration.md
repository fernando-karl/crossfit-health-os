# Integração Apple HealthKit

## API

```
POST /api/v1/integrations/healthkit/sync
Authorization: Bearer <access_token>
Content-Type: application/json
```

### Corpo (JSON)

```json
{
  "type": "daily_recovery",
  "device": "Apple Watch",
  "start_date": "2026-06-17T06:00:00Z",
  "end_date": "2026-06-17T07:00:00Z",
  "hrv_rmssd_ms": 62,
  "resting_heart_rate_bpm": 54,
  "sleep_duration_hours": 7.2,
  "sleep_quality_score": 78
}
```

### Resposta

```json
{
  "status": "success",
  "records_synced": 1,
  "recovery_metric_updated": true,
  "metric_date": "2026-06-17",
  "readiness_score": 72
}
```

Os dados alimentam `recovery_metrics` e o motor adaptativo de treino.

---

## Opção A — App iOS nativo (recomendado)

Código em [`ios/`](../ios/README.md). Companion SwiftUI com login JWT + sync HealthKit.

---

## Opção B — Apple Shortcuts (sem Xcode)

1. Obtenha um **access token** JWT (login na web → DevTools → `localStorage.access_token`).

2. Crie um atalho **“Sync CHOS Health”**:
   - **Obter conteúdo de URL**
     - URL: `https://SUA-API/api/v1/integrations/healthkit/sync`
     - Método: POST
     - Cabeçalhos: `Authorization: Bearer SEU_TOKEN`, `Content-Type: application/json`
     - Corpo JSON: métricas do dia (preencha manualmente ou via ações Health do atalho)
   - **Automation** (opcional): executar todo dia às 7h.

3. Ações Health disponíveis no Shortcuts:
   - Find Health Samples → Heart Rate Variability
   - Find Health Samples → Resting Heart Rate
   - Find Health Samples → Sleep

> Limitação: Shortcuts expõe menos controle que o app nativo; o companion iOS agrega sono + HRV de forma mais confiável.

---

## Permissões HealthKit (app nativo)

Tipos lidos (somente leitura):

- `HKQuantityType.heartRateVariabilitySDNN`
- `HKQuantityType.restingHeartRate`
- `HKCategoryType.sleepAnalysis`

Nenhum dado é escrito de volta ao Health.

---

## Privacidade

- Payload bruto também é armazenado em `healthkit_data` (JSONB) para auditoria.
- Campos manuais (stress, soreness) **não** são sobrescritos pelo sync — apenas HRV, sono e FC quando presentes.
