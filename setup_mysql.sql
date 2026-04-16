-- ============================================
-- XB Deals — Setup MySQL (esquema normalizado)
-- ============================================
-- Ejecutar con:
--   mysql -u root -p < setup_mysql.sql
-- ============================================

CREATE DATABASE IF NOT EXISTS xbdeals
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE xbdeals;

-- ─── Tabla: juegos ──────────────────────────────────────
-- Datos del juego (independientes de la región/moneda).
-- Un registro por juego único (SKU).

CREATE TABLE IF NOT EXISTS juegos (
    sku            VARCHAR(20)  PRIMARY KEY COMMENT 'ID en Microsoft Store',
    titulo         VARCHAR(500) NOT NULL    COMMENT 'Nombre del juego',
    plataforma     VARCHAR(100)             COMMENT 'Xbox One, Xbox Series X|S, PC',
    tipo           VARCHAR(50)              COMMENT 'Game, Bundle, DLC, Add-On',
    metascore      INT                      COMMENT 'Puntaje Metacritic',
    rating         DECIMAL(3,1)             COMMENT 'Rating usuarios (0-5)',
    rating_count   INT                      COMMENT 'Cantidad de reviews',
    link           VARCHAR(1000)            COMMENT 'URL en xbdeals.net',
    imagen         VARCHAR(1000)            COMMENT 'URL imagen del juego',
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ─── Tabla: precios ─────────────────────────────────────
-- Un registro por juego + región + período de oferta.
-- Así podés tener US y AU (y las que quieras) por cada juego.
-- Incluye campos opcionales para ofertas "bonus" (Game Pass, Gold, EA Play...).

CREATE TABLE IF NOT EXISTS precios (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    sku                  VARCHAR(20)  NOT NULL COMMENT 'FK → juegos.sku',
    region               VARCHAR(10)  NOT NULL COMMENT 'Código: us, au, gb, ca...',
    moneda               VARCHAR(5)   NOT NULL COMMENT 'Código: USD, AUD, GBP...',
    precio_original      DECIMAL(10,2)         COMMENT 'Precio sin descuento',
    precio_descuento     DECIMAL(10,2)         COMMENT 'Precio con descuento regular',
    porcentaje_descuento VARCHAR(10)           COMMENT 'Ej: -60%',
    -- Oferta "bonus" (Game Pass, Gold, EA Play, etc.) — opcional
    tipo_bonus           VARCHAR(20)           COMMENT 'pass, gold, ea, etc.',
    precio_bonus         VARCHAR(20)           COMMENT 'Texto: "FREE", "$X.XX"',
    porcentaje_bonus     VARCHAR(10)           COMMENT 'Ej: -100%',
    fecha_fin_oferta     VARCHAR(100)          COMMENT '"Ends in 6 days"',
    precio_valido_hasta  DATE                  COMMENT 'Fecha exacta fin oferta',
    fecha_scrape         DATETIME     NOT NULL COMMENT 'Cuándo se scrapeó',

    UNIQUE KEY unique_price (sku, region, precio_valido_hasta),
    INDEX idx_region (region),
    INDEX idx_sku (sku),
    INDEX idx_moneda (moneda),
    INDEX idx_tipo_bonus (tipo_bonus),

    CONSTRAINT fk_precio_juego
        FOREIGN KEY (sku) REFERENCES juegos(sku)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- Consultas útiles
-- ============================================

-- Juegos GRATIS con Game Pass en US
-- SELECT j.titulo, p.porcentaje_bonus, p.precio_bonus, p.precio_original
-- FROM juegos j
-- JOIN precios p ON j.sku = p.sku
-- WHERE p.region = 'us' AND p.tipo_bonus = 'pass'
-- ORDER BY p.precio_original DESC;

-- Comparar precio US vs AU con info de bonus
-- SELECT
--     j.titulo,
--     pus.precio_descuento  AS precio_us,
--     pus.porcentaje_descuento AS desc_us,
--     pus.tipo_bonus        AS bonus_us,
--     pau.precio_descuento  AS precio_au,
--     pau.porcentaje_descuento AS desc_au,
--     pau.tipo_bonus        AS bonus_au
-- FROM juegos j
-- JOIN precios pus ON j.sku = pus.sku AND pus.region = 'us'
-- JOIN precios pau ON j.sku = pau.sku AND pau.region = 'au'
-- ORDER BY j.titulo;


-- ============================================
-- Consultas útiles
-- ============================================

-- Comparar precio US vs AU para el mismo juego
-- SELECT
--     j.titulo,
--     pus.precio_descuento  AS precio_us,
--     pau.precio_descuento  AS precio_au,
--     pus.porcentaje_descuento AS desc_us,
--     pau.porcentaje_descuento AS desc_au
-- FROM juegos j
-- JOIN precios pus ON j.sku = pus.sku AND pus.region = 'us'
-- JOIN precios pau ON j.sku = pau.sku AND pau.region = 'au'
-- ORDER BY j.titulo;

-- Juegos que están en oferta en AU pero no en US
-- SELECT j.titulo, p.precio_descuento, p.porcentaje_descuento
-- FROM juegos j
-- JOIN precios p ON j.sku = p.sku AND p.region = 'au'
-- WHERE j.sku NOT IN (SELECT sku FROM precios WHERE region = 'us')
-- ORDER BY j.titulo;

-- Mejores ofertas por región
-- SELECT region, j.titulo, p.porcentaje_descuento, p.precio_descuento
-- FROM precios p
-- JOIN juegos j ON j.sku = p.sku
-- ORDER BY region, (p.precio_original - p.precio_descuento) DESC;

-- Resumen por región
-- SELECT
--     region,
--     moneda,
--     COUNT(*) AS total_ofertas,
--     ROUND(AVG(precio_descuento), 2) AS precio_promedio,
--     MIN(precio_descuento) AS precio_minimo
-- FROM precios
-- GROUP BY region, moneda;
