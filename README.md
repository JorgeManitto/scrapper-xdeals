# 🎮 XB Deals Scraper

Scraper para extraer ofertas de juegos de Xbox desde [xbdeals.net](https://xbdeals.net/us-store/discounts).

Extrae: título, precio original, precio con descuento, porcentaje de descuento, plataformas, tipo, link e imagen.

---

## 📋 Requisitos previos

Necesitás tener **Python 3.10 o superior** instalado.

### 1. Instalar Python

#### Windows

1. Ir a [python.org/downloads](https://www.python.org/downloads/)
2. Descargar la última versión (botón amarillo grande)
3. **IMPORTANTE:** al instalar, marcar la casilla ✅ **"Add Python to PATH"**
4. Click en "Install Now"
5. Verificar abriendo **CMD** o **PowerShell** y escribiendo:
   ```
   python --version
   ```

#### macOS

```bash
# Opción 1: Descargar desde python.org/downloads
# Opción 2: Con Homebrew (si lo tenés):
brew install python
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

---

### 2. Descargar el proyecto

Descargá los archivos del proyecto y abrilos en una carpeta. Necesitás estos archivos:

```
xbdeals-scraper/
├── scraper.py          ← El scraper principal
├── requirements.txt    ← Las dependencias
└── README.md           ← Este archivo
```

---

### 3. Instalar dependencias

Abrí una terminal/CMD **dentro de la carpeta del proyecto** y ejecutá:

```bash
# (Opcional pero recomendado) Crear un entorno virtual:
python -m venv venv

# Activar el entorno virtual:
# En Windows:
venv\Scripts\activate
# En macOS/Linux:
source venv/bin/activate

# Instalar las librerías de Python:
pip install -r requirements.txt

# Instalar el navegador Chromium para Playwright:
playwright install chromium
```

> **Nota:** El comando `playwright install chromium` descarga un navegador Chromium (~150MB). Solo hace falta hacerlo una vez.

---

## 🚀 Uso

```bash
# Scrapear TODAS las páginas de ofertas
python scraper.py

# Scrapear solo las primeras 3 páginas (para probar)
python scraper.py --pages 3

# Personalizar el nombre del archivo de salida
python scraper.py --output mis_ofertas

# Modo debug: guarda el HTML crudo para inspección
python scraper.py --debug

# Combinar opciones
python scraper.py --pages 5 --output ofertas_hoy --debug
```

### Opciones disponibles

| Opción             | Descripción                                     | Default            |
|--------------------|------------------------------------------------|--------------------|
| `--pages` o `-p`   | Número máximo de páginas a scrapear             | Todas              |
| `--output` o `-o`  | Nombre base del archivo CSV/XLSX                | `xbdeals_ofertas`  |
| `--debug` o `-d`   | Guardar HTML crudo en carpeta `debug/`          | Desactivado        |

---

## 📁 Archivos de salida

Después de ejecutar el scraper, vas a encontrar:

- **`xbdeals_ofertas.csv`** — Datos en formato CSV (se abre con Excel, Google Sheets, etc.)
- **`xbdeals_ofertas.xlsx`** — Datos en formato Excel (requiere `openpyxl`)
- **`debug/`** — (solo con `--debug`) HTML crudo de cada página

### Columnas del CSV

| Columna                | Descripción                          |
|------------------------|--------------------------------------|
| `titulo`               | Nombre del juego                     |
| `precio_original`      | Precio sin descuento                 |
| `precio_descuento`     | Precio con descuento                 |
| `porcentaje_descuento` | Porcentaje de descuento (ej: -75%)   |
| `plataformas`          | Plataformas compatibles              |
| `tipo`                 | Tipo (game, DLC, bundle)             |
| `link`                 | URL del juego en xbdeals             |
| `imagen`               | URL de la imagen del juego           |
| `fecha_scrape`         | Fecha y hora del scraping            |

---

## 🔧 Solución de problemas

### "No se encontraron tarjetas de juegos"

El sitio puede haber cambiado su estructura HTML. Ejecutá con `--debug`:

```bash
python scraper.py --pages 1 --debug
```

Luego abrí `debug/page_1.html` en un navegador e inspeccioná la estructura de las tarjetas de juegos para ajustar los selectores CSS en `scraper.py`.

### "playwright install" falla

```bash
# Probar instalando dependencias del sistema (Linux):
playwright install-deps chromium
playwright install chromium
```

### El sitio bloquea las peticiones

El scraper ya incluye medidas para evitar detección (User-Agent real, pausas entre páginas). Si aun así te bloquean, podés:

1. Aumentar las pausas editando `time.sleep()` en el script
2. Ejecutar en modo NO headless cambiando `headless=True` a `headless=False` en el script

---

## ⚖️ Aviso legal

Este scraper es para uso personal y educativo. Respetá los términos de servicio del sitio web y usalo de manera responsable. No sobrecargues el servidor con peticiones excesivas.
