# 📍 Monitor de Eventos y Noticias - Chapela y Redondela

Monitor automatizado en Python diseñado para vigilar diariamente y en tiempo real la publicación de nuevos eventos, noticias y artículos sobre **Chapela** y **Redondela** en las principales fuentes locales de ocio y agenda cultural de la comarca, notificando al instante a través de un bot de Telegram.

---

## 🌐 Fuentes Monitorizadas

1. **VigoPeques** ([vigopeques.com](https://www.vigopeques.com/)):
   - Canal RSS oficial (`/feed/`) para novedades inmediatas.
   - Portada web y carruseles destacados.
   - Buscador temático integrado.

2. **Metropolitano - Agenda** ([metropolitano.gal/agenda/](https://metropolitano.gal/agenda/)):
   - Conexión directa a la API oficial de eventos (EventON REST API).
   - Detección de títulos, descripciones completas, fechas y enlaces de cada evento.

3. **Metropolitano - Qué Hacer** ([metropolitano.gal/seccion/que-hacer/](https://metropolitano.gal/seccion/que-hacer/)):
   - API de publicaciones de la categoría de ocio y eventos culturales.
   - Extracción de artículos completos y extractos.

4. **Concello de Redondela - Axenda Completa** ([redondela.gal/agenda/categoria/axenda-completa/](https://redondela.gal/agenda/categoria/axenda-completa/)):
   - Conexión oficial vía The Events Calendar REST API del Concello.
   - Extracción de convocatorias culturales, contacontos, festivales, clubes de lectura y exposiciones en Redondela y Chapela.

---

## 🚀 Características Principales

- **Detección inteligente de términos**: Búsqueda exacta por límites de palabra (`\b(chapela|redondela)\b`), insensible a mayúsculas/minúsculas, tanto en títulos como en el cuerpo de la noticia.
- **Deduplicación canónica**: Limpieza de parámetros de analítica (`utm_*`, etc.) para evitar alertas repetidas de una misma noticia.
- **Alertas formateadas en Telegram**:
  - Etiqueta de la zona (`#Chapela` / `#Redondela`).
  - Fuente origen (VigoPeques, Metropolitano Agenda, Qué Hacer).
  - Título y fragmento relevante de texto centrado en la palabra encontrada.
  - Enlace directo al artículo.
- **Persistencia atómica**: Almacena el historial en `estado_articulos.json` para garantizar que cada artículo nuevo se notifica una sola vez.
- **Resiliencia HTTP**: Reintentos automáticos ante cortes puntuales de red o caídas de los servidores.

---

## 📦 Instalación

1. Clona o abre el directorio del proyecto:
   ```bash
   cd chapela-redondela-monitor
   ```

2. Instala las dependencias necesarias:
   ```bash
   pip install -r requirements.txt
   ```

3. El archivo `.env` ya viene configurado con las credenciales de tu bot:
   ```env
   TELEGRAM_TOKEN=tu_token_aqui
   TELEGRAM_CHAT_ID=tu_chat_id_aqui
   KEYWORDS=Chapela,Redondela
   ```

---

## 🏃 Ejecución Manual

Puedes ejecutarlo en cualquier momento desde la consola:
```bash
python monitor.py
```
O simplemente haciendo doble clic en el archivo ejecutable:
```text
run_monitor.bat
```

---

## ⏰ Modos de Ejecución

El bot está diseñado para operar principalmente en **Render** como servidor 24/7 con Webhook de Telegram.

### Opción 1 (Recomendada): En la nube 24/7 con Render (Web Service + Webhook Instantáneo)

El repositorio incluye el archivo [`render.yaml`](file:///C:/Users/fran_/.gemini/antigravity/scratch/chapela-redondela-monitor/render.yaml) para desplegar el bot en **Render**:
- **Respuestas instantáneas**: Configura el webhook autenticado de Telegram (`secret_token`) automáticamente para responder a `/eventos`, `/start` y `/ayuda` en menos de 1 segundo.
- **Scraping continuo**: Incluye un hilo en segundo plano que revisa novedades cada 30 minutos y avisa a los suscriptores.
- **Healthcheck**: Endpoint `/` con estado y contadores en tiempo real.

Para desplegarlo en Render:
1. En tu panel de Render, pulsa **New** > **Blueprint** y conecta el repositorio `franfolgar/chapela-redondela-monitor`.
2. Añade las variables de entorno secretas:
   - `TELEGRAM_TOKEN`: Tu token de bot de Telegram.
   - `TELEGRAM_CHAT_ID`: Tu ID de chat administrador.
   - `SUBSCRIBERS_SEED`: (Opcional) IDs de suscriptores iniciales separados por coma (ej. `12345678,87654321`).
3. ¡Listo! Render desplegará el servicio y configurará el Webhook automáticamente.

---

### Opción 2: Pruebas aisladas en GitHub Actions (Manual)

El archivo `.github/workflows/monitor.yml` está disponible para pruebas manuales bajo demanda desde la pestaña **Actions** de GitHub (`workflow_dispatch`). Al operar con Webhook en Render, los cron jobs automáticos de Actions están desactivados para evitar conflictos de Telegram y alertas duplicadas.

---

### Opción 3: Ejecución local en Windows

Para pruebas en local sin webhook:
```powershell
# Ejecución puntual:
python monitor.py

# O en segundo plano:
run_monitor.bat
```
