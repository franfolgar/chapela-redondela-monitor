#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitor de Artículos y Eventos - Chapela y Redondela
====================================================
Vigila periódicamente las webs:
  - https://www.vigopeques.com/
  - https://metropolitano.gal/agenda/
  - https://metropolitano.gal/seccion/que-hacer/

Filtro estricto: En Metropolitano solo se procesan las secciones 'Agenda' y 'Qué Hacer',
excluyendo de forma taxativa noticias de 'Enfoque', política, sucesos o actualidad general.
"""

import os
import sys
import json
import logging
import re
import html
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Set, Any, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ==============================================================================
# CONFIGURACIÓN Y ENTORNO
# ==============================================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

raw_keywords = os.getenv("KEYWORDS", "Chapela,Redondela")
KEYWORDS = [k.strip() for k in raw_keywords.split(",") if k.strip()]

DATA_FILE = BASE_DIR / "estado_articulos.json"
LOG_FILE = BASE_DIR / "monitor.log"

MONTH_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ChapelaMonitor")


# ==============================================================================
# UTILIDADES Y FILTRADO ESTRICTO DE SECCIONES
# ==============================================================================

def create_session() -> requests.Session:
    """Crea una sesión HTTP con reintentos automáticos y headers realistas."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,gl;q=0.8,en;q=0.7",
    })
    return session


def clean_url(url: str) -> str:
    """Normaliza y limpia parámetros de tracking (utm_*, ref, etc.) de una URL."""
    if not url:
        return ""
    parsed = urlparse(url)
    clean_path = parsed.path
    if not clean_path.endswith("/") and "." not in clean_path.split("/")[-1]:
        clean_path += "/"
    return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", ""))


def is_allowed_section(url: str) -> bool:
    """
    Filtro estricto solicitado:
    - En Metropolitano: EXCLUSIVAMENTE '/agenda/' y '/que-hacer/'.
      Quedan terminantemente excluidas '/enfoque/', '/extra/', noticias políticas o de sucesos.
    - En VigoPeques: todo el dominio vigopeques.com es apto.
    """
    if not url:
        return False

    if "metropolitano.gal" in url:
        # Exclusión taxativa de secciones no deseadas
        for forbidden in ["/enfoque/", "/extra/", "/actualidad/", "/opinion/", "/economia/"]:
            if forbidden in url:
                return False

        # Solo admitir agenda y que-hacer
        if not ("/agenda/" in url or "/que-hacer/" in url):
            return False

    return True


def strip_html(raw_html: str) -> str:
    """Elimina etiquetas HTML y limpia espacios duplicados."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return html.unescape(" ".join(text.split()))


def escape_telegram_html(text: str) -> str:
    """Escapa caracteres reservados en mensajes con formato HTML para Telegram."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def extract_matched_keywords(text: str, keywords: List[str]) -> List[str]:
    """Devuelve la lista de palabras clave encontradas."""
    matched = []
    for kw in keywords:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            matched.append(kw.capitalize())
    return sorted(list(set(matched)))


def extract_snippet(text: str, matched_keywords: List[str], max_chars: int = 180) -> str:
    """Extrae un fragmento de texto centrado en la palabra clave encontrada."""
    if not text or not matched_keywords:
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    for kw in matched_keywords:
        match = re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE)
        if match:
            start_pos = max(0, match.start() - 60)
            end_pos = min(len(text), match.end() + 100)
            snippet = text[start_pos:end_pos].strip()
            if start_pos > 0:
                snippet = "..." + snippet
            if end_pos < len(text):
                snippet = snippet + "..."
            return snippet

    return text[:max_chars] + ("..." if len(text) > max_chars else "")


def clean_date_display(raw_date: str) -> str:
    """Formatea la fecha de forma humana y legible en español."""
    if not raw_date:
        return "Fecha por confirmar"
    txt = raw_date.strip()
    txt = re.sub(r"^(?:el|del)\s+", "", txt, flags=re.I)
    txt = re.sub(r"\(GMT[^)]*\)", "", txt)
    txt = re.sub(r"\s*-\s*.*$", "", txt)  # Conservar hora inicial si es un rango
    # Insertar 'de' si falta (ej: '24 octubre' -> '24 de octubre')
    txt = re.sub(
        r"(\d{1,2})\s+([a-zA-Záéíóú]+)",
        lambda m: f"{m.group(1)} de {m.group(2)}" if m.group(2).lower() in MONTH_MAP else m.group(0),
        txt
    )
    return txt.capitalize().strip()


def extract_event_date(session: requests.Session, url: str, title: str, content: str, pub_date: str) -> Tuple[str, Optional[date]]:
    """
    Determina la fecha del evento extrayéndola de los metadatos de EventON
    o analizando las menciones de fecha en el texto.
    """
    event_date_str = ""
    dt_key = None

    # 1. Si es enlace de la agenda de Metropolitano, consultar la ficha de EventON
    if "/agenda/" in url:
        try:
            resp = session.get(url, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                el = soup.select_one(".evo_eventcard_time_t, .evocard_box.time, .evo_metarow_time")
                if el:
                    raw = strip_html(el.get_text(" ", strip=True))
                    raw = re.sub(r"^Fecha\s*", "", raw, flags=re.I)
                    raw = re.sub(r"\(GMT[^)]*\)", "", raw).strip()
                    event_date_str = raw
        except Exception as e:
            logger.debug(f"No se pudo extraer caja EventON de {url}: {e}")

    # 2. Si no hay fecha de EventON, buscar fechas en el título y contenido
    blob = f"{title}. {content}"
    if not event_date_str:
        all_matches = re.findall(
            r"(\b(?:(?:el|del)\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)?\s*,?\s*\d{1,2}(?:\s*(?:y|,|al|-)\s*\d{1,2})?\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de\s+\d{4})?)",
            blob,
            re.I
        )
        for m in all_matches:
            m_month = re.search(
                r"(\d{1,2})\s*(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)",
                m,
                re.I
            )
            if m_month:
                day = int(m_month.group(1))
                month_name = m_month.group(2).lower()
                month = MONTH_MAP.get(month_name)
                year = 2026
                m_yr = re.search(r"\b(202\d)\b", m)
                if m_yr:
                    year = int(m_yr.group(1))
                if month:
                    try:
                        k = date(year, month, day)
                        if k >= date.today():
                            event_date_str = m
                            dt_key = k
                            break
                    except ValueError:
                        pass

        if not event_date_str and all_matches:
            event_date_str = all_matches[0]

    # Calcular dt_key si aún no se tiene
    if event_date_str and dt_key is None:
        m_month = re.search(
            r"(\d{1,2})\s*(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)",
            event_date_str,
            re.I
        )
        if m_month:
            day = int(m_month.group(1))
            month_name = m_month.group(2).lower()
            month = MONTH_MAP.get(month_name)
            year = 2026
            m_yr = re.search(r"\b(202\d)\b", event_date_str)
            if m_yr:
                year = int(m_yr.group(1))
            if month:
                try:
                    dt_key = date(year, month, day)
                except ValueError:
                    pass

    # Fallback: fecha de publicación
    if not event_date_str:
        if pub_date:
            try:
                dt_obj = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                event_date_str = dt_obj.strftime("%d/%m/%Y")
                dt_key = dt_obj.date()
            except Exception:
                event_date_str = pub_date[:10]
        else:
            event_date_str = "Próximamente"

    return clean_date_display(event_date_str), dt_key


# ==============================================================================
# EXTRACTORES DE CONTENIDO (EXCLUSIVAMENTE AGENDA Y QUÉ HACER)
# ==============================================================================

def fetch_metropolitano_agenda(session: requests.Session) -> List[Dict[str, Any]]:
    """Extrae exclusivamente los eventos de la agenda oficial de Metropolitano.gal."""
    items = []
    url = "https://metropolitano.gal/wp-json/wp/v2/ajde_events?per_page=50"
    try:
        logger.info("Consultando agenda de Metropolitano.gal (EventON API)...")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        events = resp.json()
        for ev in events:
            link = clean_url(ev.get("link", ""))
            if not is_allowed_section(link):
                continue

            raw_title = ev.get("title", {}).get("rendered", "")
            raw_content = ev.get("content", {}).get("rendered", "")
            items.append({
                "id": str(ev.get("id")),
                "url": link,
                "title": strip_html(raw_title),
                "content": strip_html(raw_content),
                "source": "Metropolitano (Agenda)",
                "date": ev.get("date", ""),
            })
        logger.info(f"Metropolitano Agenda: {len(items)} eventos válidos obtenidos.")
    except Exception as e:
        logger.error(f"Error consultando agenda de Metropolitano: {e}")
    return items


def fetch_metropolitano_que_hacer(session: requests.Session) -> List[Dict[str, Any]]:
    """Extrae artículos de la sección 'Qué hacer' de Metropolitano.gal (Categoría 169)."""
    items = []
    url = "https://metropolitano.gal/wp-json/wp/v2/posts?categories=169&per_page=50"
    try:
        logger.info("Consultando sección Qué Hacer de Metropolitano.gal...")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        posts = resp.json()
        for p in posts:
            link = clean_url(p.get("link", ""))
            if not is_allowed_section(link):
                continue

            raw_title = p.get("title", {}).get("rendered", "")
            raw_excerpt = p.get("excerpt", {}).get("rendered", "")
            raw_content = p.get("content", {}).get("rendered", "")
            items.append({
                "id": str(p.get("id")),
                "url": link,
                "title": strip_html(raw_title),
                "content": f"{strip_html(raw_excerpt)} {strip_html(raw_content)}".strip(),
                "source": "Metropolitano (Qué Hacer)",
                "date": p.get("date", ""),
            })
        logger.info(f"Metropolitano Qué Hacer: {len(items)} artículos válidos obtenidos.")
    except Exception as e:
        logger.error(f"Error consultando Qué Hacer de Metropolitano: {e}")
    return items


def fetch_vigopeques_rss(session: requests.Session) -> List[Dict[str, Any]]:
    """Extrae artículos del feed RSS oficial de VigoPeques."""
    import xml.etree.ElementTree as ET

    items = []
    url = "https://www.vigopeques.com/feed/"
    try:
        logger.info("Consultando feed RSS de VigoPeques...")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            desc = item.find("description").text if item.find("description") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""

            content_encoded = ""
            for child in item:
                if child.tag.endswith("encoded"):
                    content_encoded = child.text or ""
                    break

            full_desc = f"{strip_html(desc)} {strip_html(content_encoded)}".strip()
            clean_link = clean_url(link)

            items.append({
                "id": clean_link,
                "url": clean_link,
                "title": strip_html(title),
                "content": full_desc,
                "source": "VigoPeques",
                "date": pub_date,
            })
        logger.info(f"VigoPeques Feed: {len(items)} artículos obtenidos.")
    except Exception as e:
        logger.error(f"Error consultando feed de VigoPeques: {e}")
    return items


def fetch_vigopeques_tag_redondela(session: requests.Session) -> List[Dict[str, Any]]:
    """Extrae artículos del feed temático de Redondela en VigoPeques."""
    import xml.etree.ElementTree as ET

    items = []
    url = "https://www.vigopeques.com/tag/redondela/feed/"
    try:
        logger.info("Consultando feed temático de Redondela en VigoPeques...")
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""

                content_encoded = ""
                for child in item:
                    if child.tag.endswith("encoded"):
                        content_encoded = child.text or ""
                        break

                full_desc = f"{strip_html(desc)} {strip_html(content_encoded)}".strip()
                clean_link = clean_url(link)

                items.append({
                    "id": clean_link,
                    "url": clean_link,
                    "title": strip_html(title),
                    "content": full_desc,
                    "source": "VigoPeques (Redondela)",
                    "date": pub_date,
                })
            logger.info(f"VigoPeques Tag Redondela: {len(items)} artículos obtenidos.")
    except Exception as e:
        logger.warning(f"Error consultando tag Redondela de VigoPeques: {e}")
    return items


def fetch_vigopeques_searches(session: requests.Session, keywords: List[str]) -> List[Dict[str, Any]]:
    """Scrapea los resultados del buscador de VigoPeques para Chapela y Redondela."""
    items = []
    for kw in keywords:
        url = f"https://www.vigopeques.com/?s={kw}"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                for art in soup.find_all("article"):
                    a_el = art.find("a", href=True)
                    if not a_el:
                        continue
                    link = clean_url(a_el["href"])
                    heading = art.find(["h1", "h2", "h3", "h4"])
                    title = heading.get_text(strip=True) if heading else (a_el.get("title") or "")
                    items.append({
                        "id": link,
                        "url": link,
                        "title": strip_html(title),
                        "content": strip_html(art.get_text(" ", strip=True)),
                        "source": "VigoPeques",
                        "date": "",
                    })
        except Exception as e:
            logger.warning(f"Error en búsqueda VigoPeques ({kw}): {e}")
    return items


def fetch_vigopeques_home(session: requests.Session) -> List[Dict[str, Any]]:
    """Scrapea la portada de VigoPeques para encontrar artículos destacados."""
    items = []
    url = "https://www.vigopeques.com/"
    try:
        logger.info("Consultando portada web de VigoPeques...")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        articles = soup.find_all("article")
        for art in articles:
            a_el = art.find("a", href=True)
            if not a_el:
                continue
            link = clean_url(a_el["href"])

            title = ""
            if a_el.get("title"):
                title = a_el["title"].strip()
            else:
                img_el = art.find("img", alt=True)
                if img_el and img_el.get("alt"):
                    title = img_el["alt"].strip()
                else:
                    heading = art.find(["h1", "h2", "h3", "h4"])
                    if heading:
                        title = heading.get_text(strip=True)

            text_content = art.get_text(" ", strip=True)

            items.append({
                "id": link,
                "url": link,
                "title": strip_html(title),
                "content": strip_html(text_content),
                "source": "VigoPeques",
                "date": "",
            })
        logger.info(f"VigoPeques Portada: {len(items)} artículos escaneados.")
    except Exception as e:
        logger.error(f"Error consultando portada de VigoPeques: {e}")
    return items


# ==============================================================================
# PROCESAMIENTO Y DEDUPLICACIÓN
# ==============================================================================

def get_all_matched_articles() -> List[Dict[str, Any]]:
    """
    Obtiene artículos exclusivamente de Agenda, Qué Hacer y VigoPeques,
    filtrando rigurosamente contra 'Enfoque' o noticias no relacionadas.
    """
    session = create_session()

    raw_items = []
    # 1. Metropolitano: Exclusivamente Agenda y Qué Hacer
    raw_items.extend(fetch_metropolitano_agenda(session))
    raw_items.extend(fetch_metropolitano_que_hacer(session))

    # 2. VigoPeques: Feed general, tag específico de Redondela, portada y buscador
    raw_items.extend(fetch_vigopeques_rss(session))
    raw_items.extend(fetch_vigopeques_tag_redondela(session))
    raw_items.extend(fetch_vigopeques_home(session))
    raw_items.extend(fetch_vigopeques_searches(session, KEYWORDS))

    # Deduplicar por URL canónica
    deduped_by_url: Dict[str, Dict[str, Any]] = {}
    for item in raw_items:
        url = item.get("url")
        if not url or not is_allowed_section(url):
            continue

        if url not in deduped_by_url:
            deduped_by_url[url] = item
        else:
            existing = deduped_by_url[url]
            if len(item.get("title", "")) > len(existing.get("title", "")):
                existing["title"] = item["title"]
            existing["content"] = f"{existing.get('content', '')} {item.get('content', '')}".strip()
            if not existing.get("date") and item.get("date"):
                existing["date"] = item["date"]

    matched_articles = []
    for url, article in deduped_by_url.items():
        search_blob = f"{article.get('title', '')} {article.get('content', '')}"
        matches = extract_matched_keywords(search_blob, KEYWORDS)
        if matches:
            article["matched_keywords"] = matches
            article["snippet"] = extract_snippet(article.get("content", ""), matches)

            # Extraer fecha del evento
            event_date, dt_key = extract_event_date(
                session=session,
                url=article.get("url", ""),
                title=article.get("title", ""),
                content=article.get("content", ""),
                pub_date=article.get("date", "")
            )
            article["event_date"] = event_date
            article["event_date_key"] = dt_key.isoformat() if dt_key else None
            matched_articles.append(article)

    logger.info(f"Total eventos/planes filtrados coincidentes con {KEYWORDS}: {len(matched_articles)}")
    return matched_articles


# ==============================================================================
# PERSISTENCIA DE ESTADO
# ==============================================================================

def load_previous_state(filepath: Path) -> Dict[str, Any]:
    """Carga el estado de artículos previamente registrados."""
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al leer {filepath}: {e}. Se reiniciará el estado.")
        return {}


def save_current_state(filepath: Path, state: Dict[str, Any]) -> None:
    """Guarda atómicamente el estado actual en disco."""
    temp_file = filepath.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    temp_file.replace(filepath)
    logger.info(f"Estado actualizado en {filepath} con {len(state.get('articulos', {}))} registros.")


# ==============================================================================
# SISTEMA DE NOTIFICACIONES TELEGRAM
# ==============================================================================

def send_telegram_message(message: str) -> bool:
    """Envía un mensaje con formato HTML al bot de Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Credenciales de Telegram no configuradas en el archivo .env.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        logger.info("Notificación enviada a Telegram con éxito.")
        return True
    except Exception as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")
        return False


def format_article_message(article: Dict[str, Any]) -> str:
    """
    Genera el mensaje para un nuevo evento detectado.
    Muestra la fecha del evento y el título enlazado.
    """
    event_date = escape_telegram_html(article.get("event_date", "Fecha por confirmar"))
    title = escape_telegram_html(article.get("title", "Sin título"))
    source = escape_telegram_html(article.get("source", "Web"))
    url = article.get("url", "")
    snippet = escape_telegram_html(article.get("snippet", ""))

    snippet_block = f"\n💬 <i>\"{snippet}\"</i>\n" if snippet else ""

    message = (
        f"📢 <b>NUEVO EVENTO DETECTADO</b>\n\n"
        f"📅 [<b>{event_date}</b>] <a href=\"{url}\">{title}</a>\n"
        f"🏷 <b>Fuente:</b> {source}\n"
        f"{snippet_block}\n"
        f"🔗 <a href=\"{url}\">Abrir en la web oficial</a>\n"
        f"⏰ <i>Detectado: {datetime.now().strftime('%d/%m/%Y %H:%M')}</i>"
    )
    return message


def send_future_events_summary(articles: List[Dict[str, Any]]) -> bool:
    """
    Filtra los eventos con fecha futura (de hoy en adelante),
    exclusivamente de Agenda, Qué Hacer y VigoPeques,
    los ordena cronológicamente y envía la cartelera por Telegram.
    """
    today = date.today()
    future_events = []
    seen_urls = set()

    for art in articles:
        if not is_allowed_section(art.get("url", "")):
            continue

        date_key_str = art.get("event_date_key")
        if date_key_str:
            try:
                dt_key = date.fromisoformat(date_key_str)
                if dt_key >= today and art["url"] not in seen_urls:
                    seen_urls.add(art["url"])
                    future_events.append({
                        "dt_key": dt_key,
                        "event_date": art.get("event_date", ""),
                        "title": art.get("title", ""),
                        "url": art.get("url", ""),
                        "source": art.get("source", "")
                    })
            except Exception:
                pass

    # Ordenar cronológicamente
    future_events.sort(key=lambda x: x["dt_key"])

    if not future_events:
        logger.info("No se encontraron eventos futuros en las publicaciones actuales.")
        return False

    lineas = []
    for ev in future_events:
        d = escape_telegram_html(ev["event_date"])
        t = escape_telegram_html(ev["title"])
        u = ev["url"]
        lineas.append(f"• [<b>{d}</b>] <a href=\"{u}\">{t}</a>")

    items_text = "\n\n".join(lineas)

    message = (
        f"📅 <b>AGENDA & QUÉ HACER - EVENTOS FUTUROS</b>\n\n"
        f"Convocatorias y planes publicados para Chapela y Redondela:\n\n"
        f"{items_text}\n\n"
        f"🔔 <i>Recibirás un aviso inmediato con cada nuevo evento que se publique.</i>"
    )
    return send_telegram_message(message)


# ==============================================================================
# EJECUCIÓN PRINCIPAL
# ==============================================================================

def run(force_future_summary: bool = False):
    logger.info("=================================================================")
    logger.info(f"Iniciando monitorización: Chapela & Redondela ({datetime.now().isoformat()})")
    logger.info("=================================================================")

    current_matches = get_all_matched_articles()
    previous_state = load_previous_state(DATA_FILE)

    # Limpiar cualquier artículo previo que perteneciese a 'Enfoque' o secciones prohibidas
    cleaned_saved_articles = {}
    for url, art in previous_state.get("articulos", {}).items():
        if is_allowed_section(url):
            cleaned_saved_articles[url] = art

    is_first_run = "articulos" not in previous_state
    now_iso = datetime.now().isoformat()

    if is_first_run:
        logger.info("Primera ejecución detectada. Inicializando base de artículos...")
        new_state = {
            "created_at": now_iso,
            "last_check": now_iso,
            "total_registrados": len(current_matches),
            "articulos": {},
        }
        for art in current_matches:
            new_state["articulos"][art["url"]] = {
                "title": art["title"],
                "source": art["source"],
                "event_date": art.get("event_date", ""),
                "event_date_key": art.get("event_date_key"),
                "first_seen": now_iso,
                "notified_at": now_iso,
            }

        save_current_state(DATA_FILE, new_state)
        send_future_events_summary(current_matches)
        logger.info("Monitor inicializado con éxito y resumen de eventos futuros enviado.")
        return

    if force_future_summary:
        logger.info("Enviando resumen de eventos futuros a petición...")
        send_future_events_summary(current_matches)

    # Comprobación de artículos nuevos
    new_articles = []
    for art in current_matches:
        url = art["url"]
        if url not in cleaned_saved_articles:
            new_articles.append(art)

    logger.info(f"Nuevos eventos/planes encontrados: {len(new_articles)}")

    if new_articles:
        for art in new_articles:
            logger.info(f"Notificando nuevo evento: {art['title']} [{art.get('event_date')}] ({art['url']})")
            msg = format_article_message(art)
            sent = send_telegram_message(msg)
            if sent:
                cleaned_saved_articles[art["url"]] = {
                    "title": art["title"],
                    "source": art["source"],
                    "event_date": art.get("event_date", ""),
                    "event_date_key": art.get("event_date_key"),
                    "first_seen": now_iso,
                    "notified_at": now_iso,
                }

        previous_state["last_check"] = now_iso
        previous_state["total_registrados"] = len(cleaned_saved_articles)
        previous_state["articulos"] = cleaned_saved_articles
        save_current_state(DATA_FILE, previous_state)
        logger.info(f"Se han notificado {len(new_articles)} eventos nuevos.")
    else:
        # Asegurar actualización de metadatos de fechas
        for art in current_matches:
            url = art["url"]
            if url in cleaned_saved_articles:
                cleaned_saved_articles[url]["event_date"] = art.get("event_date", "")
                cleaned_saved_articles[url]["event_date_key"] = art.get("event_date_key")

        previous_state["last_check"] = now_iso
        previous_state["total_registrados"] = len(cleaned_saved_articles)
        previous_state["articulos"] = cleaned_saved_articles
        save_current_state(DATA_FILE, previous_state)
        logger.info("No hay nuevos eventos publicados. Todo al día.")


if __name__ == "__main__":
    send_summary = "--send-future" in sys.argv
    run(force_future_summary=send_summary)
