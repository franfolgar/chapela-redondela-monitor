#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitor de Artículos y Eventos - Chapela y Redondela
====================================================
Vigila periódicamente las webs:
  - https://www.vigopeques.com/
  - https://metropolitano.gal/agenda/
  - https://metropolitano.gal/seccion/que-hacer/

Gestión de usuarios y suscriptores:
  - Detecta a cualquier nuevo usuario que pulse /start en Telegram.
  - Le da la bienvenida de forma personalizada y le envía la cartelera completa
    de todos los eventos futuros publicados para que no se pierda nada.
  - Transmite los nuevos eventos automáticamente a todos los usuarios suscritos.
"""

import os
import sys
import json
import logging
import re
import html
import time
import threading
import hashlib
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Set, Any, Optional, Tuple
from urllib.parse import urlparse, urlunparse, parse_qs, urlsplit
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler

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
SUBSCRIBERS_FILE = BASE_DIR / "suscriptores.json"
LOG_FILE = BASE_DIR / "monitor.log"
MAX_FUTURE_DAYS = 60  # Ventana máxima de eventos futuros a mostrar (próximos 2 meses)
DATA_LOCK = threading.Lock()  # Previene condiciones de carrera en lectura/escritura concurrente

MONTH_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

DAYS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MONTHS_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

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
    Filtro estricto:
    - Metropolitano: EXCLUSIVAMENTE '/agenda/' y '/que-hacer/'.
      Quedan taxativamente excluidas '/enfoque/', '/extra/', política o sucesos.
    - VigoPeques: todo el dominio vigopeques.com es apto (ocio y familia).
    """
    if not url:
        return False

    if "metropolitano.gal" in url:
        for forbidden in ["/enfoque/", "/extra/", "/actualidad/", "/opinion/", "/economia/"]:
            if forbidden in url:
                return False
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
    txt = re.sub(r"\s*-\s*.*$", "", txt)
    txt = re.sub(
        r"(\d{1,2})\s+([a-zA-Záéíóú]+)",
        lambda m: f"{m.group(1)} de {m.group(2)}" if m.group(2).lower() in MONTH_MAP else m.group(0),
        txt
    )
    return txt.capitalize().strip()


def extract_event_date(session: requests.Session, url: str, title: str, content: str, pub_date: str) -> Tuple[str, Optional[date]]:
    """Determina la fecha del evento a partir de metadatos o menciones en el texto."""
    event_date_str = ""
    dt_key = None

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
                year = date.today().year
                m_yr = re.search(r"\b(20\d{2})\b", m)
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
            year = date.today().year
            m_yr = re.search(r"\b(20\d{2})\b", event_date_str)
            if m_yr:
                year = int(m_yr.group(1))
            if month:
                try:
                    dt_key = date(year, month, day)
                except ValueError:
                    pass

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
# EXTRACTORES DE CONTENIDO
# ==============================================================================

def fetch_metropolitano_agenda(session: requests.Session) -> List[Dict[str, Any]]:
    """Extrae exclusivamente los eventos de la agenda de Metropolitano.gal."""
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
    """Extrae artículos de la sección 'Qué hacer' de Metropolitano.gal."""
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
                    "source": "VigoPeques",
                    "date": pub_date,
                })
            logger.info(f"VigoPeques Tag Redondela: {len(items)} artículos obtenidos.")
    except Exception as e:
        logger.warning(f"Error consultando tag Redondela de VigoPeques: {e}")
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


def fetch_redondela_agenda(session: requests.Session) -> List[Dict[str, Any]]:
    """Extrae eventos oficiales de la Axenda Completa de redondela.gal (The Events Calendar API)."""
    items = []
    url = f"https://redondela.gal/wp-json/tribe/events/v1/events?categories=axenda-completa&per_page=50&start_date={date.today().isoformat()}"
    try:
        logger.info("Consultando Axenda Completa de Concello de Redondela (redondela.gal)...")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events", [])
        for ev in events:
            link = clean_url(ev.get("url", ""))
            raw_title = ev.get("title", "")
            raw_desc = ev.get("description", "")
            start_date_str = ev.get("start_date", "")

            event_date = ""
            dt_key = None
            if start_date_str:
                try:
                    dt = datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S")
                    dt_key = dt.date()
                    day_name = DAYS_ES[dt.weekday()]
                    month_name = MONTHS_ES[dt.month]
                    time_part = f" ({dt.hour:02d}:{dt.minute:02d})" if (dt.hour != 0 or dt.minute != 0) else ""
                    event_date = f"{day_name}, {dt.day} de {month_name}{time_part}"
                except Exception:
                    event_date = start_date_str[:10]

            title_clean = strip_html(raw_title)
            desc_clean = strip_html(raw_desc)

            items.append({
                "id": str(ev.get("id")),
                "url": link,
                "title": title_clean,
                "content": desc_clean,
                "source": "Concello de Redondela (Axenda)",
                "event_date": event_date,
                "event_date_key": dt_key.isoformat() if dt_key else None,
                "date": ev.get("date", ""),
            })
        logger.info(f"Concello de Redondela: {len(items)} eventos obtenidos de Axenda Completa.")
    except Exception as e:
        logger.error(f"Error consultando agenda de redondela.gal: {e}")
    return items


# ==============================================================================
# PROCESAMIENTO Y DEDUPLICACIÓN
# ==============================================================================

def get_all_matched_articles(known_articles: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Obtiene artículos filtrados de Agenda, Qué Hacer, VigoPeques y Axenda de Redondela."""
    session = create_session()

    raw_items = []
    # 1. Metropolitano: Agenda y Qué Hacer
    raw_items.extend(fetch_metropolitano_agenda(session))
    raw_items.extend(fetch_metropolitano_que_hacer(session))

    # 2. VigoPeques: Feed general, tag específico de Redondela, portada y buscador
    raw_items.extend(fetch_vigopeques_rss(session))
    raw_items.extend(fetch_vigopeques_tag_redondela(session))
    raw_items.extend(fetch_vigopeques_home(session))
    raw_items.extend(fetch_vigopeques_searches(session, KEYWORDS))

    # 3. Concello de Redondela: Axenda Completa oficial
    raw_items.extend(fetch_redondela_agenda(session))

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
            if not existing.get("event_date") and item.get("event_date"):
                existing["event_date"] = item["event_date"]
                existing["event_date_key"] = item["event_date_key"]

    matched_articles = []
    for url, article in deduped_by_url.items():
        search_blob = f"{article.get('title', '')} {article.get('content', '')}"
        matches = extract_matched_keywords(search_blob, KEYWORDS)

        # Si proviene de la Axenda oficial de Redondela, pertenece por definición al municipio
        if not matches and "redondela.gal" in url:
            matches = ["Redondela"]

        if matches:
            article["matched_keywords"] = matches
            article["snippet"] = extract_snippet(article.get("content", ""), matches)

            if not article.get("event_date"):
                # Si ya está guardado en el estado previo, reutilizar fecha para evitar peticiones HTTP lentas
                if known_articles and url in known_articles and known_articles[url].get("event_date"):
                    article["event_date"] = known_articles[url]["event_date"]
                    article["event_date_key"] = known_articles[url].get("event_date_key")
                else:
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


def get_sorted_future_events(articles: List[Dict[str, Any]], max_days: int = MAX_FUTURE_DAYS) -> List[Dict[str, Any]]:
    """Filtra y ordena cronológicamente los eventos futuros dentro de la ventana de días configurada (evita eventos de 2027 o lejanos)."""
    today = date.today()
    limit_date = today + timedelta(days=max_days)
    future_events = []
    seen_urls = set()

    for art in articles:
        url = art.get("url", "")
        if not url or not is_allowed_section(url):
            continue

        date_key_str = art.get("event_date_key")
        if date_key_str:
            try:
                dt_key = date.fromisoformat(date_key_str)
                if today <= dt_key <= limit_date and url not in seen_urls:
                    seen_urls.add(url)
                    future_events.append({
                        "dt_key": dt_key,
                        "event_date": art.get("event_date", ""),
                        "title": art.get("title", ""),
                        "url": url,
                        "source": art.get("source", ""),
                    })
            except Exception:
                pass

    future_events.sort(key=lambda x: x["dt_key"])
    return future_events


def get_future_events_from_state(state: Dict[str, Any], max_days: int = MAX_FUTURE_DAYS) -> List[Dict[str, Any]]:
    """Extrae y formatea la lista de eventos futuros a partir del diccionario de artículos guardado en caché."""
    articles_list = []
    for url, data in state.get("articulos", {}).items():
        if not is_allowed_section(url):
            continue
        item = dict(data)
        item["url"] = url
        articles_list.append(item)
    return get_sorted_future_events(articles_list, max_days=max_days)


# ==============================================================================
# GESTIÓN DE SUSCRIPTORES Y PERSISTENCIA
# ==============================================================================

def load_subscribers() -> Dict[str, Any]:
    """Carga el listado de suscriptores registrados de forma segura y concurrente."""
    with DATA_LOCK:
        if not SUBSCRIBERS_FILE.exists():
            data = {}
            if TELEGRAM_CHAT_ID:
                data[TELEGRAM_CHAT_ID] = {
                    "first_name": "Admin",
                    "subscribed_at": datetime.now().isoformat()
                }
            # Semilla de suscriptores iniciales mediante variable de entorno si se configuró
            seed_ids = [s.strip() for s in os.getenv("SUBSCRIBERS_SEED", "").split(",") if s.strip()]
            for sid in seed_ids:
                if sid not in data:
                    data[sid] = {
                        "first_name": "Suscriptor",
                        "subscribed_at": datetime.now().isoformat()
                    }
            return data
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID not in data:
                    data[TELEGRAM_CHAT_ID] = {
                        "first_name": "Admin",
                        "subscribed_at": datetime.now().isoformat()
                    }
                return data
        except Exception as e:
            logger.error(f"Error al leer {SUBSCRIBERS_FILE}: {e}")
            return {}


def save_subscribers(subscribers: Dict[str, Any]) -> None:
    """Guarda atómicamente el listado de suscriptores con bloqueo de concurrencia."""
    with DATA_LOCK:
        temp_file = SUBSCRIBERS_FILE.parent / f"{SUBSCRIBERS_FILE.name}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(subscribers, f, ensure_ascii=False, indent=2)
        temp_file.replace(SUBSCRIBERS_FILE)
        logger.info(f"Listado de suscriptores actualizado con {len(subscribers)} usuarios.")


def load_previous_state(filepath: Path) -> Dict[str, Any]:
    """Carga el estado de artículos previamente registrados con bloqueo de concurrencia."""
    with DATA_LOCK:
        if not filepath.exists():
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer {filepath}: {e}. Se reiniciará el estado.")
            return {}


def save_current_state(filepath: Path, state: Dict[str, Any]) -> None:
    """Guarda atómicamente el estado actual en disco purgando artículos con más de 60 días de antigüedad."""
    with DATA_LOCK:
        # Purgar artículos antiguos para evitar crecimiento ilimitado
        cutoff_date = (date.today() - timedelta(days=60)).isoformat()
        articulos = state.get("articulos", {})
        pruned_articulos = {}
        for url, item in articulos.items():
            ev_key = item.get("event_date_key")
            first_seen = (item.get("first_seen") or "")[:10]
            ref_date = ev_key or first_seen
            if not ref_date or ref_date >= cutoff_date:
                pruned_articulos[url] = item

        state["articulos"] = pruned_articulos
        state["total_registrados"] = len(pruned_articulos)

        temp_file = filepath.parent / f"{filepath.name}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        temp_file.replace(filepath)
        logger.info(f"Estado actualizado en {filepath} con {len(pruned_articulos)} registros (purgados anteriores a {cutoff_date}).")


# ==============================================================================
# MENSAJES Y NOTIFICACIONES TELEGRAM
# ==============================================================================

def split_telegram_text(text: str, max_chars: int = 4000) -> List[str]:
    """Divide texto largo en trozos <= max_chars respetando párrafos, líneas y palabras."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for p in paragraphs:
        if len(p) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            lines = p.split("\n")
            curr_line = ""
            for line in lines:
                if len(line) > max_chars:
                    words = line.split(" ")
                    curr_word = ""
                    for w in words:
                        if len(curr_word) + len(w) + 1 > max_chars:
                            if curr_word:
                                chunks.append(curr_word.strip())
                            curr_word = w
                        else:
                            curr_word = f"{curr_word} {w}" if curr_word else w
                    if curr_word:
                        chunks.append(curr_word.strip())
                else:
                    if len(curr_line) + len(line) + 1 > max_chars:
                        if curr_line:
                            chunks.append(curr_line.strip())
                        curr_line = line
                    else:
                        curr_line = f"{curr_line}\n{line}" if curr_line else line
            if curr_line:
                chunks.append(curr_line.strip())
        else:
            if len(current_chunk) + len(p) + 2 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p
            else:
                current_chunk = f"{current_chunk}\n\n{p}" if current_chunk else p

    if current_chunk:
        chunks.append(current_chunk.strip())

    return [c for c in chunks if c.strip()]


def send_telegram_message(chat_id: str, message: str) -> bool:
    """Envía un mensaje con formato HTML a un chat concreto de Telegram, dividiendo de forma segura si excede el límite de 4096 caracteres."""
    if not TELEGRAM_TOKEN or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = split_telegram_text(message, max_chars=4000)
    success = True

    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=20)
            resp.raise_for_status()
            logger.info(f"Mensaje ({len(chunk)} chars) enviado con éxito a chat {chat_id}.")
        except Exception as e:
            logger.error(f"Error al enviar mensaje a Telegram (chat {chat_id}): {e}")
            success = False
    return success


def broadcast_telegram_message(message: str) -> None:
    """Difunde un mensaje a todos los suscriptores registrados con control de tasa de Telegram."""
    subscribers = load_subscribers()
    if not subscribers and TELEGRAM_CHAT_ID:
        send_telegram_message(TELEGRAM_CHAT_ID, message)
        return

    for cid in list(subscribers.keys()):
        send_telegram_message(cid, message)
        time.sleep(0.05)  # 50ms rate limit protection


def build_future_events_text(future_events: List[Dict[str, Any]]) -> str:
    """Construye las líneas de texto formateadas de eventos futuros."""
    if not future_events:
        return f"<i>No hay eventos programados en los próximos {MAX_FUTURE_DAYS} días.</i>"

    lineas = []
    for ev in future_events:
        d = escape_telegram_html(ev["event_date"])
        t = escape_telegram_html(ev["title"])
        u = ev["url"]
        lineas.append(f"• [<b>{d}</b>] <a href=\"{u}\">{t}</a>")

    return "\n\n".join(lineas)


def build_events_summary_message(first_name: str, future_events: List[Dict[str, Any]]) -> str:
    """Construye la respuesta directa para el comando /eventos o /agenda."""
    nombre = f", <b>{escape_telegram_html(first_name)}</b>" if first_name else ""
    cartelera = build_future_events_text(future_events)
    return (
        f"📅 <b>CARTELERA DE EVENTOS - CHAPELA Y REDONDELA</b> 📍\n\n"
        f"Próximos planes y citas confirmadas para las próximas semanas{nombre}:\n\n"
        f"{cartelera}\n\n"
        f"🔔 <i>Te avisaremos al instante con cada nuevo evento en cuanto se publique.</i>"
    )


def build_welcome_message(first_name: str, future_events: List[Dict[str, Any]]) -> str:
    """
    Construye el mensaje de bienvenida completo para nuevos usuarios,
    incluyendo la cartelera de eventos futuros para que no se pierdan nada.
    """
    nombre_limpio = escape_telegram_html(first_name or "vecino/a")
    cartelera = build_future_events_text(future_events)

    message = (
        f"👋 ¡Hola, <b>{nombre_limpio}</b>! Bienvenido/a al <b>Bot de Eventos de Chapela y Redondela</b> 📍\n\n"
        f"A continuación tienes la <b>cartelera de los próximos eventos</b> confirmados en la comarca para que no te pierdas ninguno:\n\n"
        f"{cartelera}\n\n"
        f"🔔 <b>¿Cómo funciona?</b>\n"
        f"Cada vez que se publique una nueva fiesta, magosto, festival o plan cultural en <b>Metropolitano</b>, <b>VigoPeques</b> o la <b>Axenda do Concello de Redondela</b>, recibirás un aviso automático al momento por aquí.\n\n"
        f"<i>¡Disfruta de los planes de nuestra tierra!</i>"
    )
    return message


def format_article_message(article: Dict[str, Any]) -> str:
    """Genera el mensaje para un nuevo evento detectado."""
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


# ==============================================================================
# GESTIÓN DE ACTUALIZACIONES TELEGRAM (NUEVOS USUARIOS /START Y COMANDOS)
# ==============================================================================

def get_webhook_secret() -> str:
    """Obtiene o genera un token seguro para autenticar las peticiones del webhook de Telegram."""
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not secret and TELEGRAM_TOKEN:
        # Generar hash determinista de 32 caracteres alfanuméricos válido para Telegram
        secret = hashlib.sha256(f"telegram_secret_salt_{TELEGRAM_TOKEN}".encode()).hexdigest()[:32]
    return secret


def configure_telegram_webhook(base_url: str) -> bool:
    """Configura el webhook de Telegram con secret_token apuntando a Render."""
    if not TELEGRAM_TOKEN or not base_url:
        return False
    webhook_url = f"{base_url.rstrip('/')}/webhook"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    secret_token = get_webhook_secret()
    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "drop_pending_updates": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            logger.info(f"Webhook de Telegram autenticado (con secret_token) configurado hacia: {webhook_url}")
            return True
        else:
            logger.error(f"Fallo al configurar webhook en Telegram: {data}")
            return False
    except Exception as e:
        logger.error(f"Error llamando a setWebhook: {e}")
        return False


def delete_telegram_webhook() -> bool:
    """Elimina el webhook de Telegram para permitir getUpdates / long polling sin conflictos."""
    if not TELEGRAM_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook"
    try:
        resp = requests.post(url, timeout=10)
        return resp.json().get("ok", False)
    except Exception:
        return False


def handle_single_update(
    up: Dict[str, Any],
    future_events: List[Dict[str, Any]],
    subscribers: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Procesa una actualización individual de Telegram (/start, /eventos, /ayuda, etc.).
    Devuelve True si se registró o modificó algún suscriptor.
    """
    msg = up.get("message") or up.get("my_chat_member")
    if not msg:
        return False

    chat = msg.get("chat", {})
    cid = str(chat.get("id", ""))
    from_user = msg.get("from", {})
    first_name = from_user.get("first_name", "")
    username = from_user.get("username", "")
    text = (msg.get("text") or "").strip().lower()

    if not cid:
        return False

    save_immediately = False
    if subscribers is None:
        subscribers = load_subscribers()
        save_immediately = True

    is_new_user = cid not in subscribers
    is_start_cmd = text.startswith("/start")
    is_events_cmd = text.startswith("/eventos") or text.startswith("/agenda") or text.startswith("/cartelera")
    is_help_cmd = text.startswith("/ayuda") or text.startswith("/help")

    user_changed = False

    if is_new_user:
        logger.info(f"Nuevo suscriptor detectado: {first_name} (@{username}) [ID: {cid}]")
        subscribers[cid] = {
            "first_name": first_name,
            "username": username,
            "subscribed_at": datetime.now().isoformat(),
            "last_interaction": datetime.now().isoformat(),
        }
        user_changed = True
        welcome_msg = build_welcome_message(first_name, future_events)
        send_telegram_message(cid, welcome_msg)

    elif is_events_cmd:
        logger.info(f"Comando de eventos de {first_name} [ID: {cid}]")
        subscribers[cid]["last_interaction"] = datetime.now().isoformat()
        user_changed = True
        summary_msg = build_events_summary_message(first_name, future_events)
        send_telegram_message(cid, summary_msg)

    elif is_start_cmd:
        logger.info(f"Comando /start de suscriptor existente: {first_name} [ID: {cid}]")
        subscribers[cid]["last_interaction"] = datetime.now().isoformat()
        user_changed = True
        welcome_msg = build_welcome_message(first_name, future_events)
        send_telegram_message(cid, welcome_msg)

    elif is_help_cmd:
        logger.info(f"Comando de ayuda de {first_name} [ID: {cid}]")
        help_msg = (
            "ℹ️ <b>BOT DE EVENTOS DE CHAPELA Y REDONDELA</b> 📍\n\n"
            "Comandos disponibles:\n"
            "• /eventos - Cartelera de las próximas semanas.\n"
            "• /start - Mensaje de bienvenida e información inicial.\n"
            "• /ayuda - Muestra esta ayuda.\n\n"
            "<i>Recibirás un aviso automático en cuanto se detecte cualquier nuevo evento en Chapela o Redondela.</i>"
        )
        send_telegram_message(cid, help_msg)

    if user_changed and save_immediately:
        save_subscribers(subscribers)

    return user_changed


def process_telegram_updates(future_events: List[Dict[str, Any]], poll_timeout: int = 0) -> None:
    """
    Consulta getUpdates en Telegram:
    - Identifica a nuevos usuarios que hayan iniciado el bot (/start).
    - Responde al instante a /eventos, /start o /ayuda.
    - Soporta long polling mediante poll_timeout para respuesta en tiempo real sin latencia.
    - Confirma los mensajes procesados con offset para no duplicar.
    """
    if not TELEGRAM_TOKEN:
        return

    subscribers = load_subscribers()
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {}
    if poll_timeout > 0:
        params["timeout"] = poll_timeout

    try:
        req_timeout = (poll_timeout + 5) if poll_timeout > 0 else 10
        resp = requests.get(url, params=params, timeout=req_timeout)
        data = resp.json()
        if not data.get("ok"):
            if data.get("error_code") == 409:
                logger.debug("Webhook activo en Telegram; consulta getUpdates omitida para evitar conflicto 409.")
            else:
                logger.warning(f"Respuesta no OK de Telegram getUpdates: {data}")
            return

        updates = data.get("result", [])
        if not updates:
            return

        max_update_id = None
        new_users_added = False

        for up in updates:
            up_id = up.get("update_id")
            if up_id is not None:
                max_update_id = up_id if max_update_id is None else max(max_update_id, up_id)

            if handle_single_update(up, future_events, subscribers):
                new_users_added = True

        if new_users_added:
            save_subscribers(subscribers)

        # Confirmar updates procesados con offset
        if max_update_id is not None:
            requests.get(f"{url}?offset={max_update_id + 1}&limit=1", timeout=10)

    except Exception as e:
        logger.error(f"Error procesando actualizaciones de Telegram: {e}")


# ==============================================================================
# EJECUCIÓN PRINCIPAL
# ==============================================================================

def run(force_future_summary: bool = False):
    logger.info("=================================================================")
    logger.info(f"Iniciando monitorización: Chapela & Redondela ({datetime.now().isoformat()})")
    logger.info("=================================================================")

    # PASO 1: Cargar estado previo y responder a Telegram DE INMEDIATO (< 1 seg)
    # Evita que el usuario tenga que esperar mientras se consultan las webs.
    previous_state = load_previous_state(DATA_FILE)
    cached_future_events = get_future_events_from_state(previous_state)
    process_telegram_updates(cached_future_events)

    # PASO 2: Consultar fuentes web para detectar nuevos eventos
    known_articles = previous_state.get("articulos", {})
    current_matches = get_all_matched_articles(known_articles=known_articles)
    future_events = get_sorted_future_events(current_matches)

    # PASO 3: Procesar Telegram de nuevo por si entraron comandos durante el scrape
    process_telegram_updates(future_events)

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
        # En servidor Render no spamear a todos con la cartelera completa en reinicios de contenedor;
        # los usuarios ya pueden consultarla en cualquier momento con /eventos
        if not os.getenv("RENDER") and not os.getenv("PORT"):
            cartelera = build_future_events_text(future_events)
            msg = (
                "📅 <b>AGENDA & QUÉ HACER - EVENTOS FUTUROS</b>\n\n"
                f"Convocatorias y planes publicados para Chapela y Redondela (próximos {MAX_FUTURE_DAYS} días):\n\n"
                f"{cartelera}\n\n"
                "🔔 <i>Recibirás un aviso inmediato con cada nuevo evento que se publique.</i>"
            )
            broadcast_telegram_message(msg)
        logger.info("Monitor inicializado con éxito.")
        return

    if force_future_summary:
        logger.info("Difundiendo cartelera de eventos futuros a petición...")
        cartelera = build_future_events_text(future_events)
        msg = (
            "📅 <b>AGENDA & QUÉ HACER - EVENTOS FUTUROS</b>\n\n"
            f"Convocatorias y planes publicados para Chapela y Redondela (próximos {MAX_FUTURE_DAYS} días):\n\n"
            f"{cartelera}\n\n"
            "🔔 <i>Recibirás un aviso inmediato con cada nuevo evento que se publique.</i>"
        )
        broadcast_telegram_message(msg)

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
            broadcast_telegram_message(msg)
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
        logger.info(f"Se han notificado {len(new_articles)} eventos nuevos a todos los suscriptores.")
    else:
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


# ==============================================================================
# SERVIDOR WEB Y WEBHOOK PARA RENDER (24/7)
# ==============================================================================

class TelegramWebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silenciar logs ruidosos de comprobaciones automáticas /health
        if len(args) > 0 and ("GET / " in str(args[0]) or "GET /health" in str(args[0])):
            return
        logger.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))

    def do_GET(self):
        if self.path in ("/", "/health", "/ping"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            previous_state = load_previous_state(DATA_FILE)
            subscribers = load_subscribers()
            resp = {
                "status": "healthy",
                "service": "Chapela y Redondela Event Monitor Bot",
                "total_articulos": len(previous_state.get("articulos", {})),
                "total_suscriptores": len(subscribers),
                "timestamp": datetime.now().isoformat(),
            }
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/refresh"):
            # Protección contra DoS: requiere token de autenticación
            expected_secret = get_webhook_secret()
            query_token = ""
            if "?" in self.path:
                qs = parse_qs(urlsplit(self.path).query)
                query_token = qs.get("token", [""])[0]
            header_token = self.headers.get("X-Admin-Token", "")

            if expected_secret and (query_token != expected_secret and header_token != expected_secret):
                self.send_response(403)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Acceso denegado: token invalido. Use /refresh?token=...\n")
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Ejecutando escaneo manual de eventos en segundo plano...\n")
            threading.Thread(target=run, kwargs={"force_future_summary": False}, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ("/webhook", f"/webhook/{TELEGRAM_TOKEN}"):
            expected_secret = get_webhook_secret()
            received_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if expected_secret and received_secret != expected_secret:
                logger.warning("Intento de acceso denegado a /webhook: secret_token ausente o invalido.")
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                if body:
                    update = json.loads(body)
                    previous_state = load_previous_state(DATA_FILE)
                    future_events = get_future_events_from_state(previous_state)

                    # Salvaguarda: si por reinicio de contenedor el archivo aún no tiene eventos,
                    # hacer escaneo de rescate inmediato para no devolver cartelera vacía
                    if not future_events:
                        logger.info("Cartelera vacía en petición de Telegram; ejecutando escaneo de rescate...")
                        current_matches = get_all_matched_articles(known_articles=previous_state.get("articulos", {}))
                        future_events = get_sorted_future_events(current_matches)
                        if current_matches:
                            threading.Thread(target=run, kwargs={"force_future_summary": False}, daemon=True).start()

                    handle_single_update(update, future_events)
            except Exception as e:
                logger.error(f"Error procesando webhook entrante de Telegram: {e}")

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


def run_web_server(port: int = 10000):
    """
    Servidor web para Render (Web Service 24/7):
    - Escucha en el puerto asignado por Render ($PORT).
    - GET /: Healthcheck para Render y monitores de disponibilidad.
    - POST /webhook: Respuesta instantánea a /eventos, /start, etc.
    - Hilo secundario: Comprueba nuevos eventos cada 30 minutos.
    """
    logger.info("=================================================================")
    logger.info(f"Iniciando Servidor Web para Render en puerto {port}")
    logger.info("=================================================================")

    # Si estamos en Render, configurar el webhook automáticamente
    external_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL")
    if external_url:
        configure_telegram_webhook(external_url)
    else:
        logger.info("RENDER_EXTERNAL_URL no configurado aún (normal en arranque local o primer despliegue).")

    # Si la base de eventos está vacía, ejecutar escaneo síncrono para tener la cartelera lista de inmediato
    previous_state = load_previous_state(DATA_FILE)
    if not previous_state.get("articulos"):
        logger.info("Base de eventos vacía al arrancar. Ejecutando escaneo inicial de artículos...")
        try:
            run(force_future_summary=False)
        except Exception as e:
            logger.error(f"Error en escaneo inicial síncrono: {e}")

    # Hilo secundario: Scraper automático cada 30 minutos
    def periodic_scraper():
        logger.info("Hilo secundario de scraping activado (revisión periódica cada 30 min).")
        while True:
            try:
                time.sleep(1800)
                logger.info("Ejecutando ciclo periódico de comprobación de eventos desde Render...")
                run(force_future_summary=False)
            except Exception as e:
                logger.error(f"Error en ciclo periódico de scraping: {e}")

    scraper_thread = threading.Thread(target=periodic_scraper, daemon=True)
    scraper_thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", port), TelegramWebhookHandler)
    logger.info(f"Servidor HTTP activo en http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Servidor detenido por el usuario.")
    finally:
        server.server_close()


# ==============================================================================
# MODO ESCUCHA EN TIEMPO REAL (DAEMON / POLLING LOCAL)
# ==============================================================================

def run_listener_loop():
    """
    Bucle de escucha interactivo en tiempo real con long polling.
    Permite responder a /start, /eventos y comandos en menos de 0.5 segundos de forma continua.
    """
    logger.info("Iniciando bucle de escucha en tiempo real de Telegram (long-polling)...")
    delete_telegram_webhook()
    previous_state = load_previous_state(DATA_FILE)
    future_events = get_future_events_from_state(previous_state)
    last_scrape = 0.0

    while True:
        try:
            # Cada 30 minutos refrescar eventos raspando las webs
            if time.time() - last_scrape > 1800:
                current_matches = get_all_matched_articles(known_articles=previous_state.get("articulos", {}))
                future_events = get_sorted_future_events(current_matches)
                last_scrape = time.time()

            # Long polling con timeout=20s (devuelve respuesta instantánea si llega un comando)
            process_telegram_updates(future_events, poll_timeout=20)
        except KeyboardInterrupt:
            logger.info("Escucha detenida por el usuario.")
            break
        except Exception as e:
            logger.error(f"Error en bucle de escucha: {e}")
            time.sleep(3)


if __name__ == "__main__":
    if "--server" in sys.argv or "--web" in sys.argv or os.getenv("RENDER"):
        port = int(os.getenv("PORT", 10000))
        run_web_server(port)
    elif "--listen" in sys.argv or "--daemon" in sys.argv:
        run_listener_loop()
    else:
        send_summary = "--send-future" in sys.argv
        run(force_future_summary=send_summary)
