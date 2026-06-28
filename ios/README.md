# CrossFit Health OS — iOS HealthKit Companion

App nativo mínimo (SwiftUI) que lê HRV, sono e FC de repouso do Apple Health e envia para:

`POST /api/v1/integrations/healthkit/sync`

## Requisitos

- Xcode 15+ / iOS 17+
- iPhone com Apple Watch (recomendado para HRV e sono)
- Conta no CrossFit Health OS (mesmo login da web)

## Setup no Xcode

1. **File → New → Project → iOS App**
   - Product Name: `CrossFitHealthOS`
   - Interface: SwiftUI
   - Language: Swift
   - Bundle ID: `com.seudominio.crossfithealthos` (ou o seu)

2. **Substitua/copie** os arquivos de [`CrossFitHealthOS/`](CrossFitHealthOS/) para o target do projeto.

3. **Capabilities → HealthKit** — marque HealthKit.

4. **Info.plist** — use as chaves de [`CrossFitHealthOS/Resources/Info.plist`](CrossFitHealthOS/Resources/Info.plist) (`NSHealthShareUsageDescription`, etc.).

5. **Signing** — configure Team + provisioning profile.

6. Build & Run no dispositivo físico (HealthKit não funciona no simulador para dados reais).

## Configuração no app

1. Abra o app no iPhone.
2. Informe a **URL da API** (ex.: `https://crossfit.seudominio.com` ou `http://127.0.0.1:8003` em dev).
3. Faça login com e-mail/senha da web.
4. Toque em **Autorizar Health** e depois **Sincronizar agora**.

O app agenda sync automático ao abrir (foreground) e via Background App Refresh quando habilitado.

## Payload enviado

| Campo | Origem HealthKit |
|-------|------------------|
| `hrv_rmssd_ms` | HRV (SDNN/RMSSD disponível) |
| `resting_heart_rate_bpm` | Resting Heart Rate |
| `sleep_duration_hours` | Sleep Analysis (última noite) |
| `sleep_quality_score` | Estimativa 0–100 a partir das fases de sono |
| `start_date` / `end_date` | ISO 8601 do dia da métrica |

## Alternativa sem build: Apple Shortcuts

Veja [`docs/healthkit_integration.md`](../docs/healthkit_integration.md) para um atalho iOS que chama a API com JWT.

## Troubleshooting

- **401 Unauthorized** — token expirado; faça login novamente no app.
- **Sem HRV** — Apple Watch precisa registrar HRV durante o sono; aguarde 1–2 noites.
- **SDNN vs RMSSD** — o backend aceita ambos no campo `hrv_rmssd_ms`; valores são comparados ao baseline rolling de 30 dias.
