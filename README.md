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

## ⏰ Programación Automática

Tienes dos formas de dejarlo funcionando de manera 100% automática:

### Opción 1: En tu ordenador Windows (Programador de Tareas)

Para que se ejecute todos los días a las **10:00 AM**:
```powershell
schtasks /create /tn "ChapelaRedondelaMonitor" /tr "C:\Users\fran_\.gemini\antigravity\scratch\chapela-redondela-monitor\run_monitor.bat" /sc daily /st 10:00 /f
```

O si prefieres que revise varias veces al día (por ejemplo cada 4 horas):
```powershell
schtasks /create /tn "ChapelaRedondelaMonitor" /tr "C:\Users\fran_\.gemini\antigravity\scratch\chapela-redondela-monitor\run_monitor.bat" /sc hourly /mo 4 /f
```

*(Si en el futuro deseas borrar la tarea programada: `schtasks /delete /tn "ChapelaRedondelaMonitor" /f`)*

---

### Opción 2: En la nube con GitHub Actions (Gratis 24/7 sin encender el PC)

El repositorio incluye el archivo listo en `.github/workflows/monitor.yml`.
Está configurado para ejecutarse automáticamente **6 veces al día** (cada 4 horas: sobre las 09:25, 13:25, 17:25, 21:25, 01:25 y 05:25 hora española peninsular):

1. Sube este repositorio a tu cuenta de GitHub (`franfolgar/chapela-redondela-monitor`).
2. Los secretos de Telegram (`TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`) se configuran automáticamente en **Settings** -> **Secrets and variables** -> **Actions**.
3. Se ejecutará todos los días en los servidores de GitHub sin depender de tener el ordenador encendido.
