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

### Opción 1 (Recomendada): Automatización Programada Cada 15 Minutos en GitHub Actions (100% Gratis, 0 Horas de Servidor)

El bot está configurado para ejecutarse automáticamente mediante **GitHub Actions** **cada 15 minutos**:
- **Frecuencia**: Cada 15 minutos (`*/15 * * * *`: :00, :15, :30, :45).
- **Respuesta a comandos**: Los usuarios que escriban `/eventos` o pulsen `/start` recibirán la respuesta en un plazo máximo de 15 minutos.
- **Filtro temporal estricto**: Solo emite alertas por Telegram si el evento tendrá lugar en los **próximos 60 días (2 meses)** o si es una noticia general de última hora (publicada en los últimos 7 días). Cualquier evento pasado o posterior a 60 días se descarta automáticamente.

**Ventajas clave:**
- **0 horas de Render consumidas**: No gasta la cuota mensual de 750 horas de Render, dejándola disponible para otros proyectos.
- **Ilimitado en repositorios públicos**: GitHub Actions ofrece minutos ilimitados para repositorios públicos, por lo que ejecutarlo 24 veces al día tiene coste cero.
- **Persistencia en Git**: Actualiza automáticamente `estado_articulos.json` en el repositorio para no duplicar nunca alertas.
- **Suscriptores seguros**: Mantiene la lista de suscriptores privada mediante `SUBSCRIBERS_SEED` en GitHub Secrets y la caché segura de GitHub Actions, sin exponer datos personales en commits públicos.
- **Ejecución manual**: Puedes lanzar una comprobación cuando quieras desde la pestaña **Actions** en GitHub pulsando en *Run workflow*.

---

### Opción 2: Servidor 24/7 en Render (Web Service opcional)

Si se prefiere una respuesta interactiva en tiempo real (< 1 segundo a comandos `/eventos`), el repositorio incluye [`render.yaml`](file:///C:/Users/fran_/.gemini/antigravity/scratch/chapela-redondela-monitor/render.yaml). Ten en cuenta que un servicio 24/7 en Render consume unas ~720 horas/mes de la cuota compartida de tu workspace. Si se utiliza GitHub Actions, el servicio de Render puede permanecer suspendido o eliminado.

---

### Agenda del Concello de Redondela desde el PC

`redondela.gal` bloquea (403) las peticiones desde GitHub Actions y otros centros de datos. Para que el bot siga recibiendo sus eventos, un PC doméstico descarga la agenda y la sube al repositorio como `agenda_redondela.json`; si la consulta en directo falla, el monitor usa esa copia.

```powershell
# Exportar una vez (sin subir al repo):
python monitor.py --export-redondela --no-push

# Programar la exportación cada hora (commit y push solo si la agenda cambia):
powershell -ExecutionPolicy Bypass -File programar_exportacion_agenda.ps1
```

---

### Opción 3: Ejecución local en Windows

Para pruebas en local sin webhook:
```powershell
# Ejecución puntual:
python monitor.py

# O en segundo plano:
run_monitor.bat
```
