"""
XB Deals Multi-Region Scraper + MySQL
=======================================
Scrapea ofertas de Xbox desde múltiples regiones de xbdeals.net
y guarda en MySQL con estructura normalizada (juegos + precios por región).

Regiones por defecto: US (USD) y AU (AUD).
Fácil de agregar más regiones editando REGIONS.

Uso:
    python scraper.py                            # Scrapea US + AU, CSV + MySQL
    python scraper.py --regions us               # Solo US
    python scraper.py --regions us au gb         # US + AU + UK
    python scraper.py --pages 3                  # Solo 3 páginas por región
    python scraper.py --no-mysql                 # Solo CSV, sin MySQL
    python scraper.py --debug                    # Guarda HTML crudo
"""

import argparse
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
    import pandas as pd
except ImportError as e:
    print(f"❌ Falta una dependencia: {e}")
    print("   Ejecutá: pip install -r requirements.txt")
    print("   Y luego: playwright install chromium")
    sys.exit(1)


# ─── Regiones disponibles ────────────────────────────────────────────────────
# Agregá más regiones acá. El código de región es el prefijo de la URL.
# La moneda es informativa para el CSV/reportes.

REGIONS = {
    "us": {"name": "United States", "currency": "USD", "symbol": "$"},
    "au": {"name": "Australia",     "currency": "AUD", "symbol": "A$"},
    "gb": {"name": "United Kingdom","currency": "GBP", "symbol": "£"},
    "ca": {"name": "Canada",        "currency": "CAD", "symbol": "C$"},
    "de": {"name": "Germany",       "currency": "EUR", "symbol": "€"},
    "br": {"name": "Brazil",        "currency": "BRL", "symbol": "R$"},
    "mx": {"name": "Mexico",        "currency": "MXN", "symbol": "MX$"},
    "jp": {"name": "Japan",         "currency": "JPY", "symbol": "¥"},
    "ar": {"name": "Argentina",     "currency": "ARS", "symbol": "ARS$"},
}

DEFAULT_REGIONS = ["us", "au"]


# ─── Modelos de datos ────────────────────────────────────────────────────────

@dataclass
class GameInfo:
    """Información del juego (independiente de la región)."""
    sku: str = ""
    titulo: str = ""
    plataforma: str = ""
    tipo: str = ""
    metascore: str = ""
    rating: str = ""
    rating_count: str = ""
    link: str = ""
    imagen: str = ""


@dataclass
class RegionPrice:
    """Precio de un juego en una región específica."""
    sku: str = ""
    region: str = ""
    moneda: str = ""
    precio_original: str = ""
    precio_descuento: str = ""
    porcentaje_descuento: str = ""
    # ── Oferta bonus (Game Pass, Gold, EA Play, etc.) ──
    tipo_bonus: str = ""              # 'pass', 'gold', 'ea', etc.
    precio_bonus: str = ""            # Precio con el bonus (puede ser "FREE")
    porcentaje_bonus: str = ""        # Ej: -100%
    # ── Fechas ──
    fecha_fin_oferta: str = ""
    precio_valido_hasta: str = ""
    fecha_scrape: str = ""


@dataclass
class ScrapedDeal:
    """Resultado combinado del scraping de una tarjeta."""
    game: GameInfo = field(default_factory=GameInfo)
    price: RegionPrice = field(default_factory=RegionPrice)


# ─── Configuración ───────────────────────────────────────────────────────────

BASE_URL_TEMPLATE = "https://xbdeals.net/{region}-store/discounts"
PARAMS = "?additional_stores=0"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "xbdeals"),
}

# Modo headless — se puede cambiar con --no-headless (útil para debug local)
HEADLESS = True


# ─── Funciones auxiliares ────────────────────────────────────────────────────

def get_page_url(region: str, page_num: int) -> str:
    base = BASE_URL_TEMPLATE.format(region=region)
    if page_num == 1:
        return f"{base}{PARAMS}"
    return f"{base}/{page_num}{PARAMS}"


def save_debug_html(html: str, region: str, page_num: int, output_dir: Path) -> None:
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(exist_ok=True)
    filepath = debug_dir / f"{region}_page_{page_num}.html"
    filepath.write_text(html, encoding="utf-8")


def extract_text(element, default="") -> str:
    if element is None:
        return default
    return element.get_text(strip=True)


def extract_price_number(text: str) -> str:
    """Extrae el número de precio de un texto (ej: 'A$6.99' → 'A$6.99')."""
    if not text:
        return ""
    # Captura precios con distintos símbolos: $, A$, £, €, R$, ¥, etc.
    match = re.search(r'[A-Z]*[$£€¥]\s*[\d,.]+|[\d,.]+\s*[A-Z]{3}', text)
    if match:
        return match.group(0).strip()
    # Fallback: solo números
    match = re.search(r'[\d,.]+', text)
    return match.group(0) if match else text.strip()


# ─── Parser ──────────────────────────────────────────────────────────────────

def parse_page(html: str, region: str) -> list[ScrapedDeal]:
    """Parsea una página de xbdeals y devuelve deals con info de juego + precio."""
    soup = BeautifulSoup(html, "lxml")
    deals = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    region_info = REGIONS.get(region, {"currency": "???", "symbol": "?"})

    cards = soup.select("div.game-collection-item")
    if not cards:
        print("   ⚠️  No se encontraron tarjetas.")
        return deals

    print(f"   🔍 {len(cards)} tarjetas encontradas")

    for card in cards:
        game = GameInfo()
        price = RegionPrice(
            region=region,
            moneda=region_info["currency"],
            fecha_scrape=timestamp,
        )

        # ── Datos del juego ──
        sku_el = card.select_one('span[itemprop="sku"]')
        game.sku = extract_text(sku_el)
        price.sku = game.sku

        title_el = (
            card.select_one('span[itemprop="name"]')
            or card.select_one("span.game-collection-item-details-title")
        )
        game.titulo = extract_text(title_el)

        platform_el = card.select_one("span.game-collection-item-top-platform")
        game.plataforma = extract_text(platform_el)

        type_el = card.select_one("div.game-collection-item-type")
        game.tipo = extract_text(type_el)

        metascore_el = card.select_one("div.game-collection-item-metascore")
        game.metascore = extract_text(metascore_el)

        rating_el = card.select_one('span[itemprop="ratingValue"]')
        game.rating = extract_text(rating_el)

        rating_count_el = card.select_one('span[itemprop="ratingCount"]')
        game.rating_count = extract_text(rating_count_el)

        link_el = card.select_one("a.game-collection-item-link")
        if link_el and link_el.get("href"):
            href = link_el["href"]
            game.link = f"https://xbdeals.net{href}" if href.startswith("/") else href

        img_el = card.select_one("img.game-collection-item-image")
        if img_el:
            game.imagen = img_el.get("data-src", "") or img_el.get("src", "")

        # ── Datos de precio (específicos de la región) ──
        # El sitio puede tener:
        #   - Solo descuento regular: clase 'discount' + 'price-discount'
        #   - Solo descuento bonus:   clase 'discount-bonus' + 'price-bonus'
        #   - Ambos:  regular para todos + bonus adicional (Game Pass, Gold...)

        discount_regular_el = card.select_one("span.game-collection-item-discount")
        discount_bonus_el = card.select_one("span.game-collection-item-discount-bonus")
        price_regular_el = card.select_one("span.game-collection-item-price-discount")
        price_bonus_el = card.select_one("span.game-collection-item-price-bonus")

        # ── Descuento "principal" ──
        # Si hay bonus y regular juntos → regular es el "principal", bonus es extra
        # Si solo hay uno → ese es el principal
        if discount_regular_el and price_regular_el:
            # Caso: hay descuento regular (con o sin bonus adicional)
            price.porcentaje_descuento = extract_text(discount_regular_el)
            price.precio_descuento = extract_price_number(price_regular_el.get_text())
        elif discount_bonus_el and price_bonus_el and not discount_regular_el:
            # Caso: SOLO descuento bonus (sin descuento regular)
            # Lo tratamos como descuento principal para no perder el dato
            price.porcentaje_descuento = extract_text(discount_bonus_el)
            price.precio_descuento = extract_price_number(price_bonus_el.get_text())

        # ── Descuento bonus EXTRA (Game Pass, Gold, EA Play, etc.) ──
        # Solo lo registramos si ADEMÁS hay un descuento regular
        if discount_bonus_el and price_bonus_el and discount_regular_el:
            price.porcentaje_bonus = extract_text(discount_bonus_el)
            # El texto puede ser "FREE", "$X.XX", etc. — lo guardamos tal cual
            price.precio_bonus = price_bonus_el.get_text(strip=True)
            # Detectar el tipo de bonus por el alt del ícono
            bonus_icon = price_bonus_el.select_one("img.game-collection-item-icon-bonus")
            if bonus_icon:
                price.tipo_bonus = bonus_icon.get("alt", "").strip().lower()

        # ── Precio original (tachado) ──
        price_original_el = card.select_one(
            "span.game-collection-item-price.strikethrough"
        )
        if price_original_el:
            price.precio_original = extract_price_number(price_original_el.get_text())

        end_date_el = card.select_one("span.game-collection-item-end-date")
        price.fecha_fin_oferta = extract_text(end_date_el)

        valid_until_el = card.select_one('span[itemprop="priceValidUntil"]')
        price.precio_valido_hasta = extract_text(valid_until_el)

        if game.titulo and game.sku:
            deals.append(ScrapedDeal(game=game, price=price))

    return deals


def has_next_page(html: str, region: str, current_page: int) -> bool:
    """Verifica si existe una página siguiente en la paginación."""
    soup = BeautifulSoup(html, "lxml")
    next_page = current_page + 1
    # Buscar un link a la página siguiente
    pattern = rf'/{region}-store/discounts/{next_page}'
    for link in soup.select(f'a[href*="/{region}-store/discounts/"]'):
        if pattern in link.get("href", ""):
            return True
    # También buscar un botón/link "next" o "›"
    for link in soup.select('a.next, a[rel="next"], li.next a'):
        if link.get("href"):
            return True
    return False


# ─── MySQL ───────────────────────────────────────────────────────────────────

CREATE_JUEGOS_SQL = """
CREATE TABLE IF NOT EXISTS juegos (
    sku            VARCHAR(20) PRIMARY KEY COMMENT 'ID en Microsoft Store',
    titulo         VARCHAR(500) NOT NULL,
    plataforma     VARCHAR(100),
    tipo           VARCHAR(50),
    metascore      INT,
    rating         DECIMAL(3,1),
    rating_count   INT,
    link           VARCHAR(1000),
    imagen         VARCHAR(1000),
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_PRECIOS_SQL = """
CREATE TABLE IF NOT EXISTS precios (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    sku                  VARCHAR(20)   NOT NULL COMMENT 'FK a juegos.sku',
    region               VARCHAR(10)   NOT NULL COMMENT 'Código región (us, au, gb...)',
    moneda               VARCHAR(5)    NOT NULL COMMENT 'Código moneda (USD, AUD...)',
    precio_original      DECIMAL(10,2),
    precio_descuento     DECIMAL(10,2),
    porcentaje_descuento VARCHAR(10),
    -- Oferta bonus (Game Pass, Gold, EA Play, etc.)
    tipo_bonus           VARCHAR(20)   COMMENT 'pass, gold, ea, etc.',
    precio_bonus         VARCHAR(20)   COMMENT 'Texto: "FREE", "$X.XX", etc.',
    porcentaje_bonus     VARCHAR(10)   COMMENT 'Ej: -100%',
    fecha_fin_oferta     VARCHAR(100),
    precio_valido_hasta  DATE,
    fecha_scrape         DATETIME      NOT NULL,

    UNIQUE KEY unique_price (sku, region, precio_valido_hasta),
    INDEX idx_region (region),
    INDEX idx_sku (sku),
    INDEX idx_tipo_bonus (tipo_bonus),

    CONSTRAINT fk_precio_juego
        FOREIGN KEY (sku) REFERENCES juegos(sku)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

UPSERT_JUEGO_SQL = """
INSERT INTO juegos (sku, titulo, plataforma, tipo, metascore, rating, rating_count, link, imagen)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    titulo       = VALUES(titulo),
    plataforma   = VALUES(plataforma),
    tipo         = VALUES(tipo),
    metascore    = COALESCE(VALUES(metascore), metascore),
    rating       = COALESCE(VALUES(rating), rating),
    rating_count = COALESCE(VALUES(rating_count), rating_count),
    link         = VALUES(link),
    imagen       = VALUES(imagen);
"""

UPSERT_PRECIO_SQL = """
INSERT INTO precios (
    sku, region, moneda,
    precio_original, precio_descuento, porcentaje_descuento,
    tipo_bonus, precio_bonus, porcentaje_bonus,
    fecha_fin_oferta, precio_valido_hasta, fecha_scrape
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    precio_original      = VALUES(precio_original),
    precio_descuento     = VALUES(precio_descuento),
    porcentaje_descuento = VALUES(porcentaje_descuento),
    tipo_bonus           = VALUES(tipo_bonus),
    precio_bonus         = VALUES(precio_bonus),
    porcentaje_bonus     = VALUES(porcentaje_bonus),
    fecha_scrape         = VALUES(fecha_scrape);
"""


def parse_decimal(value: str):
    if not value:
        return None
    clean = re.sub(r'[^\d.]', '', value)
    try:
        return float(clean)
    except ValueError:
        return None


def parse_int(value: str):
    if not value:
        return None
    clean = re.sub(r'[^\d]', '', value)
    try:
        return int(clean)
    except ValueError:
        return None


def parse_date(value: str):
    if not value or len(value) < 8:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        return None


def save_to_mysql(all_deals: list[ScrapedDeal]) -> None:
    """Guarda juegos y precios en MySQL (tablas normalizadas)."""
    try:
        import mysql.connector
    except ImportError:
        print("❌ Falta mysql-connector-python.")
        print("   pip install mysql-connector-python")
        return

    cfg = MYSQL_CONFIG
    print(f"\n🗄️  Conectando a MySQL ({cfg['host']}:{cfg['port']}/{cfg['database']})...")

    try:
        conn = mysql.connector.connect(**cfg)
        cursor = conn.cursor()

        # Crear tablas
        cursor.execute(CREATE_JUEGOS_SQL)
        cursor.execute(CREATE_PRECIOS_SQL)
        conn.commit()
        print("   ✅ Tablas 'juegos' y 'precios' verificadas")

        # ── Insertar/actualizar juegos ──
        juegos_inserted = 0
        juegos_updated = 0
        seen_skus = set()

        for deal in all_deals:
            g = deal.game
            if not g.sku or g.sku in seen_skus:
                continue
            seen_skus.add(g.sku)

            cursor.execute(UPSERT_JUEGO_SQL, (
                g.sku, g.titulo, g.plataforma or None, g.tipo or None,
                parse_int(g.metascore), parse_decimal(g.rating),
                parse_int(g.rating_count),
                g.link or None, g.imagen or None,
            ))
            if cursor.rowcount == 1:
                juegos_inserted += 1
            elif cursor.rowcount == 2:
                juegos_updated += 1

        conn.commit()
        print(f"   🎮 Juegos: {juegos_inserted} nuevos, {juegos_updated} actualizados")

        # ── Insertar/actualizar precios ──
        precios_inserted = 0
        precios_updated = 0
        precios_errors = 0

        for deal in all_deals:
            p = deal.price
            if not p.sku:
                continue
            try:
                cursor.execute(UPSERT_PRECIO_SQL, (
                    p.sku, p.region, p.moneda,
                    parse_decimal(p.precio_original),
                    parse_decimal(p.precio_descuento),
                    p.porcentaje_descuento or None,
                    p.tipo_bonus or None,
                    p.precio_bonus or None,
                    p.porcentaje_bonus or None,
                    p.fecha_fin_oferta or None,
                    parse_date(p.precio_valido_hasta),
                    p.fecha_scrape,
                ))
                if cursor.rowcount == 1:
                    precios_inserted += 1
                elif cursor.rowcount == 2:
                    precios_updated += 1
            except mysql.connector.Error as e:
                precios_errors += 1
                if precios_errors <= 3:
                    print(f"   ⚠️  Error precio '{p.sku}/{p.region}': {e}")

        conn.commit()
        print(f"   💰 Precios: {precios_inserted} nuevos, {precios_updated} actualizados"
              + (f", {precios_errors} errores" if precios_errors else ""))

        # Totales
        cursor.execute("SELECT COUNT(*) FROM juegos")
        print(f"   📊 Total en 'juegos':  {cursor.fetchone()[0]} registros")
        cursor.execute("SELECT region, COUNT(*) FROM precios GROUP BY region")
        for row in cursor.fetchall():
            print(f"   📊 Total en 'precios' [{row[0].upper()}]: {row[1]} registros")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"   ❌ Error MySQL: {e}")
        print("   💡 Verificá config y que la DB exista:")
        print('   💡 mysql -u root -p -e "CREATE DATABASE xbdeals;"')


# ─── Carga de página con reintentos ──────────────────────────────────────────

MAX_RETRIES = 3

def load_page(page_obj, url: str, attempt: int = 1) -> str:
    """
    Carga una página con estrategia de espera robusta y reintentos.

    En vez de networkidle (que se cuelga si hay ads/analytics/websockets),
    usa domcontentloaded + espera explícita por las tarjetas de juegos.
    Si falla, reintenta con tiempos incrementales.
    """
    try:
        # domcontentloaded es más rápido y confiable que networkidle
        page_obj.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Esperar a que aparezcan las tarjetas de juegos (máx 15s)
        try:
            page_obj.wait_for_selector(
                "div.game-collection-item",
                timeout=15000,
                state="attached",
            )
        except Exception:
            # Si no aparecen en 15s, tal vez la página está vacía (última +1)
            pass

        # Pequeña espera para que termine de renderizar imágenes lazy, etc.
        time.sleep(1.5)

        # Scroll para disparar carga lazy de imágenes/contenido
        page_obj.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)

        return page_obj.content()

    except Exception as e:
        if attempt < MAX_RETRIES:
            wait_time = attempt * 5  # 5s, 10s, 15s...
            print(f"⏳ Reintento {attempt}/{MAX_RETRIES} en {wait_time}s...", end=" ", flush=True)
            time.sleep(wait_time)
            return load_page(page_obj, url, attempt + 1)
        else:
            raise e


# ─── Scraper principal ───────────────────────────────────────────────────────

def scrape_region(
    page_obj,
    region: str,
    max_pages: int | None,
    debug: bool,
    output_dir: Path,
) -> list[ScrapedDeal]:
    """
    Scrapea todas las páginas de una región.
    
    En vez de detectar el total de páginas al inicio (que falla porque
    la paginación del sitio solo muestra una ventana de ~7 páginas),
    avanza página por página hasta que:
      - No se encuentren más tarjetas de juegos, o
      - Se alcance el límite de --pages, o
      - No exista link a la página siguiente
    """
    region_info = REGIONS.get(region, {"name": region.upper(), "currency": "???"})
    region_name = region_info["name"]
    currency = region_info["currency"]

    print(f"\n{'─' * 50}")
    print(f"🌍 Región: {region_name} ({region.upper()}) — {currency}")
    if max_pages:
        print(f"📊 Límite: {max_pages} páginas")
    else:
        print(f"📊 Scrapeando todas las páginas disponibles...")
    print(f"{'─' * 50}")

    deals: list[ScrapedDeal] = []
    page_num = 1
    consecutive_empty = 0

    while True:
        # Verificar límite de páginas
        if max_pages and page_num > max_pages:
            print(f"\n  🛑 Límite de {max_pages} páginas alcanzado")
            break

        print(f"  📄 Página {page_num}...", end=" ", flush=True)

        try:
            url = get_page_url(region, page_num)
            html = load_page(page_obj, url)

            if debug:
                save_debug_html(html, region, page_num, output_dir)

            page_deals = parse_page(html, region)

            if not page_deals:
                consecutive_empty += 1
                print(f"⚠️  Sin resultados")
                if consecutive_empty >= 2:
                    print(f"  🏁 Fin: {consecutive_empty} páginas vacías consecutivas")
                    break
                page_num += 1
                time.sleep(1.5)
                continue

            consecutive_empty = 0
            deals.extend(page_deals)
            print(f"✅ {len(page_deals)} juegos (total: {len(deals)})")

            # Verificar si hay página siguiente
            if not has_next_page(html, region, page_num):
                print(f"  🏁 Última página alcanzada ({page_num})")
                break

        except Exception as e:
            print(f"❌ Error: {e}")
            consecutive_empty += 1
            if consecutive_empty >= 3:
                print(f"  🛑 Demasiados errores consecutivos, deteniendo región")
                break

        page_num += 1
        time.sleep(1.5)

    print(f"  📦 Total {region.upper()}: {len(deals)} deals en {page_num} páginas")
    return deals


def scrape_xbdeals(
    regions: list[str],
    max_pages: int | None = None,
    output_name: str = "xbdeals_ofertas",
    save_csv: bool = True,
    save_mysql: bool = True,
    debug: bool = False,
) -> None:
    output_dir = Path(".")
    all_deals: list[ScrapedDeal] = []

    print("🎮 XB Deals Multi-Region Scraper")
    print(f"🌍 Regiones: {', '.join(r.upper() for r in regions)}")
    print("=" * 50)

    with sync_playwright() as pw:
        print("🚀 Iniciando navegador...")
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-site-isolation-trials",
                f"--user-agent={USER_AGENT}",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Sec-Ch-Ua": '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        # ── Anti-detección: ocultar señales de automatización ──
        # Esto se ejecuta ANTES de cargar cada página en el contexto
        context.add_init_script("""
            // Ocultar navigator.webdriver (señal #1 de bot detection)
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Plugins: navegadores reales tienen plugins, headless no
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Idiomas
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Permissions API coherente
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );

            // Chrome runtime (headless no lo tiene por defecto)
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
        """)

        page = context.new_page()

        for region in regions:
            if region not in REGIONS:
                print(f"\n⚠️  Región '{region}' no reconocida. Disponibles: "
                      f"{', '.join(REGIONS.keys())}")
                continue

            region_deals = scrape_region(page, region, max_pages, debug, output_dir)
            all_deals.extend(region_deals)

            # Pausa entre regiones
            if region != regions[-1]:
                print("\n⏳ Pausa entre regiones...")
                time.sleep(3)

        browser.close()

    if not all_deals:
        print("\n⚠️  No se encontraron deals. Probá con --debug.")
        return

    # ── Deduplicar por (sku, region) ──
    seen = set()
    unique_deals = []
    for d in all_deals:
        key = (d.game.sku, d.price.region)
        if key not in seen:
            seen.add(key)
            unique_deals.append(d)
    removed = len(all_deals) - len(unique_deals)
    if removed:
        print(f"\n🧹 {removed} duplicados eliminados")
    all_deals = unique_deals

    print(f"\n{'=' * 50}")
    print(f"📦 Total: {len(all_deals)} deals en {len(regions)} región(es)")

    # ── CSV ──
    if save_csv:
        rows = []
        for d in all_deals:
            row = {
                "sku": d.game.sku,
                "titulo": d.game.titulo,
                "plataforma": d.game.plataforma,
                "tipo": d.game.tipo,
                "metascore": d.game.metascore,
                "rating": d.game.rating,
                "rating_count": d.game.rating_count,
                "region": d.price.region.upper(),
                "moneda": d.price.moneda,
                "precio_original": d.price.precio_original,
                "precio_descuento": d.price.precio_descuento,
                "porcentaje_descuento": d.price.porcentaje_descuento,
                "tipo_bonus": d.price.tipo_bonus,
                "precio_bonus": d.price.precio_bonus,
                "porcentaje_bonus": d.price.porcentaje_bonus,
                "fecha_fin_oferta": d.price.fecha_fin_oferta,
                "precio_valido_hasta": d.price.precio_valido_hasta,
                "link": d.game.link,
                "imagen": d.game.imagen,
                "fecha_scrape": d.price.fecha_scrape,
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        csv_path = output_dir / f"{output_name}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"💾 CSV: {csv_path}")

        try:
            xlsx_path = output_dir / f"{output_name}.xlsx"
            df.to_excel(xlsx_path, index=False, engine="openpyxl")
            print(f"💾 Excel: {xlsx_path}")
        except ImportError:
            pass

    # ── MySQL ──
    if save_mysql:
        save_to_mysql(all_deals)

    # ── Resumen por región ──
    print(f"\n📊 Resumen:")
    for region in regions:
        region_deals = [d for d in all_deals if d.price.region == region]
        if not region_deals:
            continue
        pcts = []
        for d in region_deals:
            m = re.search(r'\d+', d.price.porcentaje_descuento)
            if m:
                pcts.append(int(m.group()))
        info = REGIONS.get(region, {})
        print(f"   [{region.upper()}] {info.get('name', region)}: "
              f"{len(region_deals)} juegos", end="")
        if pcts:
            print(f" | Desc. promedio: {sum(pcts)/len(pcts):.0f}% | Máx: {max(pcts)}%")
        else:
            print()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="🎮 Scraper multi-región de ofertas Xbox desde xbdeals.net"
    )
    parser.add_argument(
        "--regions", "-r", nargs="+", default=DEFAULT_REGIONS,
        help=f"Regiones a scrapear (default: {' '.join(DEFAULT_REGIONS)}). "
             f"Disponibles: {', '.join(REGIONS.keys())}",
    )
    parser.add_argument("--pages", "-p", type=int, default=None,
                        help="Páginas por región (default: todas)")
    parser.add_argument("--output", "-o", type=str, default="xbdeals_ofertas",
                        help="Nombre archivo CSV (default: xbdeals_ofertas)")
    parser.add_argument("--mysql", "-m", action="store_true", default=True,
                        help="Guardar en MySQL (default: sí)")
    parser.add_argument("--no-mysql", action="store_true",
                        help="No guardar en MySQL")
    parser.add_argument("--no-csv", action="store_true",
                        help="No generar CSV")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Guardar HTML crudo en debug/")
    parser.add_argument("--no-headless", action="store_true",
                        help="Mostrar navegador (útil para debuggear — requiere desktop)")

    args = parser.parse_args()

    # Configurar modo headless
    # global HEADLESS
    HEADLESS = not args.no_headless

    scrape_xbdeals(
        regions=[r.lower() for r in args.regions],
        max_pages=args.pages,
        output_name=args.output,
        save_csv=not args.no_csv,
        save_mysql=not args.no_mysql,
        debug=args.debug,
    )