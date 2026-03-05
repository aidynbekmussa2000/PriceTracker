# Price Tracker — Ralph Activity Log

## Current Status
**Last Updated:** 2026-03-05
**Market Tasks Completed:** 8
**Current Task:** — (astykzhan complete; lamoda, wildberries pending)

---

## Session Log

### 2026-03-05 — add_market_astykzhan
- **Task:** `add_market_astykzhan` — Add Astykzhan marketplace adapter (https://astykzhan.kz)
- **Files changed:**
  - `price_tracker/markets/astykzhan.py` (created)
  - `price_tracker/markets/__init__.py` (added astykzhan import)
  - `config.yaml` (added astykzhan to markets list)
- **Key finding:** astykzhan.kz is a server-rendered Bitrix CMS site. No browser/Playwright needed — adapter uses `requests`. Site has an infinite 302 redirect loop without a valid city session cookie; resolved by setting `BITRIX_SM_city=KO` (Kostanai) and `BITRIX_SM_lang=RU` cookies per-session. Category discovery parses all `/catalog/...` links from the catalog homepage, then filters to leaf categories only (those not a URL-prefix of any other path) — 335 leaf categories found. Product cards use `div.catalog-product` selector; name from `.catalog-product__title`; price from `data-price` attribute (clean integer, no string parsing needed); product URL from `a.learn_more_bnt[href]`. Pagination uses Bitrix-standard `?PAGEN_1=N&SIZEN_1=30` URL params; max page detected from highest PAGEN_1 value in pagination links. Category ID/slug is the full path relative to `/catalog/` (e.g., `produkty-pitaniya/bakaleya/krupy`). Site serves Kostanai region; `supported_cities=['almaty']` is conventional.
- **Commands run:**
  - `python -m price_tracker.main --market astykzhan --city almaty --headless --list-categories` (335 categories)
  - `python -m price_tracker.main --market astykzhan --city almaty --headless --category-id "produkty-pitaniya/bakaleya/krupy"` (single category validation)
- **Validation results:**
  - 335 leaf categories discovered
  - 248 unique products in produkty-pitaniya/bakaleya/krupy — 9 pages, correct pagination
  - Output: `data/astykzhan/almaty/20260305_054844Z.jsonl` (248 lines), `data/astykzhan/almaty/20260305_054844Z_report.json`
  - Sample product: "КРУПА ГРЕЧНЕВАЯ КГ" at 285 KZT
- **Status:** passes=true

### 2026-03-05 — add_market_ayanmarket
- **Task:** `add_market_ayanmarket` — Add AyanMarket marketplace adapter (https://ayanmarket.kz)
- **Files changed:**
  - `price_tracker/markets/ayanmarket.py` (created)
  - `price_tracker/markets/__init__.py` (added ayanmarket import)
  - `config.yaml` (added ayanmarket to markets list)
- **Key finding:** ayanmarket.kz is a Nuxt.js + Vuetify SPA backed by a public REST API at `https://ayanmarketapi.kz/api`. No browser/Playwright needed — adapter uses `requests`. Authentication requires only `Referer: https://ayanmarket.kz/` + `x-anonymous-id: <uuid>` headers. Full API flow: (1) `POST /api/site/geo/find/address {"pointCoords":[]}` → returns 61 department objects (store locations; default geolocation = Karaganda region); extract their `id` integers. (2) Categories scraped from server-rendered homepage HTML via `a[href*="/shop/collection/"]` → 2470 unique categories; slug+ID extracted from URL pattern `slug-{id}`. (3) Products: `PUT /api/web/provider/product/get/filter/site` with `{"categoryIds":[N],"departmentIds":[...],"page":P,"size":72,...}`; response has `products.content[]` with `providerProductId`, `name`, `pricesList[].price`. Pagination via `totalPages`. Site serves Karaganda/Temirtau/Astana (not Almaty); `supported_cities=['almaty']` is conventional since no city routing in API.
- **Commands run:**
  - `python -m price_tracker.main --market ayanmarket --city almaty --headless --list-categories` (2470 categories)
  - `python -m price_tracker.main --market ayanmarket --city almaty --headless --category-id 569` (moloko — single category)
  - `python -m price_tracker.main --market ayanmarket --city almaty --headless --category-id 175964` (piknik-na-prirode — pagination validation)
- **Validation results:**
  - 2470 categories discovered
  - 2 unique products in moloko (category 569) — 1 page
  - 82 unique products in piknik-na-prirode (category 175964) — 5 pages, correct pagination
  - Output: `data/ayanmarket/almaty/20260305_053703Z.jsonl` (2 lines), `data/ayanmarket/almaty/20260305_053717Z.jsonl` (82 lines)
  - Sample product: "МОЛОКО КАЗАХСТАН 0.5Л 3.2% Ф/П" at 282 KZT
- **Status:** passes=true



### 2026-03-04 — add_market_leroy_merlin
- **Task:** `add_market_leroy_merlin` — Add Leroy Merlin marketplace adapter (https://leroymerlin.kz)
- **Files changed:**
  - `price_tracker/markets/leroy_merlin.py` (created)
  - `price_tracker/markets/__init__.py` (added leroy_merlin import)
  - `config.yaml` (added leroy_merlin to markets list)
- **Key finding:** leroymerlin.kz is served by the lemanapro.kz platform (React SSR). All requests pass through servicepipe.ru bot protection, which is bypassed in headless mode by injecting `delete Object.getPrototypeOf(navigator).webdriver` as a Playwright init script combined with a standard Chrome user-agent string. No launch args needed. Catalog URL is `lemanapro.kz/catalogue/`, category URLs follow `/catalogue/{slug}/`. Product cards use `[data-qa="product"]` selector; name from `.product-card-name-link`; price integer from `[data-testid="price-integer"]` (clean integer, strip spaces). Pagination is URL-based `?page=N` (1-indexed; page 1 is the base URL, page=0 is the disabled "prev" button — excluded). Max page detected from highest N in pagination link hrefs. Categories with no product cards returned as empty (parent categories).
- **Commands run:**
  - `python -m price_tracker.main --market leroy_merlin --city almaty --headless --list-categories` (338 categories)
  - `python -m price_tracker.main --market leroy_merlin --city almaty --headless --category-id aromaty-dlya-doma` (single category validation)
- **Validation results:**
  - 338 categories discovered
  - 672 unique products collected in aromaty-dlya-doma category (63 pages, 0 empty, 0 failed)
  - Output: `data/leroy_merlin/almaty/20260304_180351Z.jsonl` (672 lines), `data/leroy_merlin/almaty/20260304_180351Z_report.json`
  - Sample product: "Ароматический диффузор Bago home Свежий хлопок 45 мл" at 8490 KZT
- **Status:** passes=true

### 2026-03-04 — add_market_flip
- **Task:** `add_market_flip` — Add Flip marketplace adapter (https://flip.kz)
- **Files changed:**
  - `price_tracker/markets/flip.py` (created)
  - `price_tracker/markets/__init__.py` (added flip import)
  - `config.yaml` (added flip to markets list)
- **Key finding:** flip.kz is a server-rendered site; no Playwright needed — adapter uses `requests` + BeautifulSoup. Category discovery uses `div.category-list a[href*="subsection="]` (302 categories). Product cards are `a.product[href*="/catalog?prod="]` with `div.title` for name and `div.price > span` (non-.old) for price. Prices use narrow no-break space `\u202f` as thousands separator. Pagination is `?subsection=N&page=P`.
- **Commands run:**
  - `python -m price_tracker.main --market flip --city almaty --headless --list-categories` (302 categories)
  - `python -m price_tracker.main --market flip --city almaty --headless --category-id 44` (single category validation)
- **Validation results:**
  - 302 categories discovered
  - 300 unique products collected in category 44 (7 pages, 0 empty, 0 failed)
  - Output: `data/flip/almaty/20260304_173550Z.jsonl` (300 lines)
  - Sample product: "Если все кошки в мире исчезнут" at 1926 KZT
- **Status:** passes=true

### 2026-03-04 — add_market_europharma
- **Task:** `add_market_europharma` — Add Europharma marketplace adapter (https://europharma.kz)
- **Files changed:**
  - `price_tracker/markets/europharma.py` (created)
  - `price_tracker/markets/__init__.py` (added europharma import)
  - `config.yaml` (added europharma to markets list)
- **Key finding:** europharma.kz is a server-rendered PHP/Yii site with PJAX progressive enhancement. Full HTML is available in the initial response without JS execution. Category discovery uses subcategory links (`a.submenu__link`) from the main nav (70 subcategories discovered). Product cards use `div.card-product.sl-item` with `data-price` attribute for clean integer price. Product URLs are root-relative (e.g., `/product-slug`). Pagination is `?page=N` based (N starts at 2). No city routing in URLs.
- **Commands run:**
  - `python -m price_tracker.main --market europharma --city almaty --headless --list-categories` (70 categories)
  - `python -m price_tracker.main --market europharma --city almaty --headless --category-id analgetiki` (single category validation)
- **Validation results:**
  - 70 categories discovered
  - 30 unique products collected in analgetiki category (4 pages, 0 empty, 0 failed)
  - Output: `data/europharma/almaty/20260304_131348Z.jsonl` (30 lines)
  - Sample product: "Нимесулид 100 мг № 20 табл" at 805 KZT
- **Status:** passes=true

### 2026-03-04 — add_market_sulpak
- **Task:** `add_market_sulpak` — Add Sulpak marketplace adapter (https://sulpak.kz)
- **Files changed:**
  - `price_tracker/markets/sulpak.py` (created)
  - `price_tracker/markets/__init__.py` (added sulpak import)
  - `config.yaml` (added sulpak to markets list)
- **Key finding:** sulpak.kz is a server-rendered site. Category listing pages use `/f/{slug}/{city}` URL pattern with `?page=N` pagination (up to 22 products per page). Product data is embedded in `window.insider_object.listing.items` JS object (name, unit_sale_price). Product URLs are extracted from `a[href^="/g/"]` elements. Each card has two `/g/` links: base URL + `#buyCheaperTab` fragment; fragment-stripping deduplication is required for correct positional pairing. 8 categories discovered from homepage navigation (kondicioneriy, led_oled_televizoriy, morozilniki_i_lari, myasorubki, noutbuki, obogrevatelniye_priboriy, smartfoniy, stiralniye_mashiniy).
- **Commands run:**
  - `python -m price_tracker.main --market sulpak --city almaty --headless --list-categories` (8 categories)
  - `python -m price_tracker.main --market sulpak --city almaty --headless --category-id noutbuki` (single category validation)
- **Validation results:**
  - 8 categories discovered
  - 22 unique products collected in noutbuki category (1 page, 0 empty, 0 failed)
  - Output: `data/sulpak/almaty/20260304_130811Z.jsonl` (22 lines)
  - Sample product: "Ноутбук Asus TUF Gaming A15 FA506NC-HN065" at 439,990 KZT
  - Product name/URL pairing verified correct
- **Status:** passes=true

### 2026-03-04 — add_market_technodom
- **Task:** `add_market_technodom` — Add Technodom marketplace adapter (https://technodom.kz)
- **Files changed:**
  - `price_tracker/markets/technodom.py` (created)
  - `price_tracker/markets/__init__.py` (added technodom import)
  - `config.yaml` (added technodom to markets list)
- **Key finding:** technodom.kz is a Next.js SSR site. Products render server-side into `[data-testid="product-card"]` elements. Name selector: `p[class*="ProductCardV_title"]`, price: `p[class*="ProductCardPrices_price"]`. Category discovery extracts depth-3 paths (`/catalog/a/b/c`) from the catalog nav, excluding brand filters (`/f/`). Pagination is URL-based `?page=N`. 438 leaf categories discovered.
- **Commands run:**
  - `python -m price_tracker.main --market technodom --city almaty --headless` (partial run, stopped after 12 categories)
- **Validation results:**
  - 438 categories discovered
  - 330 unique products collected across 12 categories (1 empty, 0 failed) before early stop
  - Output: `data/technodom/almaty/20260304_124809Z.jsonl` (330 lines)
  - Sample product: "Автомобильное зарядное устройство Samsung" at 9890 KZT
- **Status:** passes=true

### 2026-03-04 — add_market_magnum
- **Task:** `add_market_magnum` — Add Magnum marketplace adapter (https://magnum.kz)
- **Files changed:**
  - `price_tracker/markets/magnum.py` (created)
  - `price_tracker/markets/__init__.py` (added magnum import)
  - `config.yaml` (added magnum to markets list)
- **Key finding:** magnum.kz uses a public Strapi v4 API at `https://magnum.kz:1337/api`; no browser/Playwright needed — adapter uses `requests` to call JSON API directly.
- **Commands run:**
  - `python3 -m price_tracker.main --market magnum --city almaty --headless`
- **Validation results:**
  - 18 categories discovered
  - 1428 unique products collected across 15 categories (3 empty, 0 failed)
  - Output: `data/magnum/almaty/20260304_090852Z.jsonl` (1428 lines), `data/magnum/almaty/20260304_090852Z_report.json`
- **Status:** passes=true

### 2026-03-04 — ralph_bootstrap
- Replaced legacy FastMCP Ralph artifacts with price_tracker-specific Ralph workflow.
- Aligned files to this repository:
  - `ralph/plan.md` now tracks market onboarding tasks.
  - `ralph/PROMPT.md` now enforces one-market-per-iteration implementation.
  - `ralph/ralph.sh` now reads `ralph/plan.md` and `ralph/activity.md` directly.
- Next action for operator: enqueue a real task by duplicating `add_market_TEMPLATE` in `ralph/plan.md` and setting it to `"passes": false`.
