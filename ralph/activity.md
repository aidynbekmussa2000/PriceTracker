# Price Tracker — Ralph Activity Log

## Current Status
**Last Updated:** 2026-03-04
**Market Tasks Completed:** 5
**Current Task:** add_market_leroy_merlin (next pending)

---

## Session Log

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
