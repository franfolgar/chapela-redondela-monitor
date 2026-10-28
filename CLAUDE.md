# Monitor de eventos · Chapela y Redondela

Bot Python (`monitor.py`) que vigila VigoPeques (RSS/web), Metropolitano (API EventON y sección "Qué hacer") y la agenda del Concello de Redondela, filtra por `KEYWORDS` (límites de palabra) y avisa por Telegram a los suscriptores.

## Ejecutar
- `pip install -r requirements.txt`
- Una pasada: `python monitor.py` · modo servidor/escucha: `python monitor.py --server` (`iniciar_escucha_segundo_plano.bat`)

## Configuración
`.env` (no versionado; plantilla en `.env.example`): `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `KEYWORDS`. En Render también `SUBSCRIBERS_SEED`.
`suscriptores.json` es local y está ignorado (hay copia de respaldo en `C:\Users\fran_\chapela-redondela-backup`).

## Producción
- GitHub Actions (`.github/workflows/monitor.yml`) cada 15 min + `repository_dispatch` (cron externo); restaura `suscriptores.json` desde la caché de Actions y hace commit de `estado_articulos.json`.
- Render (`render.yaml`): servicio web `chapela-redondela-bot` con `python monitor.py --server`.
- Haz `git pull` antes de trabajar: CI hace commits automáticos ("chore: actualizar registro de eventos [skip ci]").

## Notas
- Repo **público**: nunca commitear `.env`, tokens ni `suscriptores.json`.
