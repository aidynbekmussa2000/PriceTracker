# Price Tracker — Ralph Activity Log

## Current Status
**Last Updated:** 2026-03-04
**Market Tasks Completed:** 2
**Current Task:** add_market_sulpak (next pending)

---

## Session Log

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
