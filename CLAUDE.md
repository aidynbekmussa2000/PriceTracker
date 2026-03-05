# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**arbuz_parsing** is a multi-marketplace price tracker for Kazakh e-commerce sites. The core system (`price_tracker/`) discovers product categories and scrapes price data from multiple online marketplaces, outputting normalized JSONL and JSON reports.

**Legacy Code**: `parser_arbuz.py`, `orchestrator_arbuz.py`, and `debug_arbuz/` are older single-marketplace scrapers for arbuz.kz. These are not used by the current system.

## Architecture

### Core System: `price_tracker/`

The system follows a **market-agnostic adapter pattern** with three layers:

1. **Runner** (`core/runner.py`): Orchestrates the crawl
   - Single `Chromium` browser instance shared across all markets/cities
   - Launches each market adapter and calls `discover_categories()` then `crawl_category()` for each
   - Manages retry logic (default: 2 retries per category)
   - Writes output via `Storage`
   - Market registry: adapters register themselves via `register_market(name, cls)`

2. **BaseMarket** (`markets/base.py`): Contract for all adapters
   - Each market subclass implements:
     - `market_name` (str) — identifier used in file paths, e.g. `'arbuz'`, `'magnum'`
     - `supported_cities` (list) — which cities this market serves, e.g. `['almaty', 'aktau']`
     - `discover_categories(city)` → `List[CategoryInfo]` — list all crawlable categories
     - `crawl_category(category, city, run_id)` → `List[PriceObservation]` — scrape one category (handles pagination)
   - Each adapter gets a fresh browser context per category via `_new_context()`
   - Locale is set to `ru-RU`, viewport `1280×900`
   - **Implementation choice**: Use Playwright + BeautifulSoup for JS-rendered sites (e.g., arbuz, lamoda) or `requests` + BeautifulSoup for server-rendered HTML (e.g., astykzhan, flip). For public APIs (e.g., magnum.kz, ayanmarket.kz), use `requests` directly without Playwright to reduce overhead.

3. **Storage** (`core/storage.py`): Handles output
   - Appends `PriceObservation` objects to per-market per-city JSONL files: `data/{market}/{city}/{timestamp}Z.jsonl`
   - Writes per-market per-city JSON report: `data/{market}/{city}/{timestamp}Z_report.json`
   - Output schema: `market`, `city`, `category_id`, `product_url`, `name`, `price_current`, `unit_code`, `pack_qty`, `captured_at`, etc.

### Adding a New Market

**Two approaches:**

1. **Manual Implementation** (for custom/complex requirements):
   - Create `price_tracker/markets/your_market.py` with a `BaseMarket` subclass
   - Implement all abstract methods: `market_name`, `supported_cities`, `discover_categories()`, `crawl_category()`
   - Register via `register_market('your_market', YourMarketClass)` at module level
   - Import the module in `price_tracker/markets/__init__.py`
   - Add market name to `config.yaml` under `markets:` list
   - Test with `python -m price_tracker.main --market your_market --city almaty --list-categories`

2. **Ralph Loop (Autonomous Implementation)**:
   - Uses `./ralph/ralph.sh` to invoke Claude agent for each market
   - Add a task to `ralph/plan.md` with `"passes": false` (duplicate `add_market_TEMPLATE`)
   - Run `bash -c 'unset CLAUDECODE && ./ralph/ralph.sh 10'`
   - Agent implements, tests, commits, and logs findings to `ralph/activity.md` per iteration
   - See [Ralph Loop Workflow](#ralph-loop-workflow-market-expansion) below for details

## Common Commands

### Run All Markets (from config)
```bash
python -m price_tracker.main
```

### Run Single Market + City
```bash
python -m price_tracker.main --market magnum --city almaty
python -m price_tracker.main --market sulpak --city aktau
```

### List Categories (Don't Crawl)
```bash
python -m price_tracker.main --list-categories --market technodom --city almaty
```

### Single Category (Useful for Testing)
```bash
python -m price_tracker.main --market flip --city almaty --category-id 44
```

### Visible Browser (for Debugging)
```bash
python -m price_tracker.main --market europharma --city almaty --no-headless
```

### Enable Debug Output (screenshots/HTML)
```bash
python -m price_tracker.main --market leroy_merlin --city almaty --debug
```

### Custom Config File
```bash
python -m price_tracker.main --config custom_config.yaml
```

## Ralph Loop Workflow (Market Expansion)

The `ralph/` directory contains the "Ralph Wiggum" autonomous agent loop for adding new markets without manual intervention.

**Files:**
- `ralph/plan.md` — JSON task list; each market addition is one task with `"passes": false/true/"in_progress"`
- `ralph/activity.md` — dated log of completed tasks and key findings per market
- `ralph/PROMPT.md` — the prompt sent to Claude each iteration (defines the workflow)
- `ralph/ralph.sh` — bash loop that invokes `claude` CLI for each iteration with fresh context

**To run the loop:**
```bash
bash -c 'unset CLAUDECODE && ./ralph/ralph.sh 10'  # up to 10 iterations
```

**Workflow per iteration:**
1. Agent reads `activity.md` (current state)
2. Finds first task with `"passes": false` in `plan.md`
3. Changes it to `"passes": "in_progress"`
4. Implements the market adapter (creates file, registers it, tests via CLI)
5. If successful: updates task to `"passes": true`, logs to `activity.md`, commits
6. Loop continues until no more `"passes": false` tasks

**To add a market to the queue:**
1. Duplicate the `add_market_TEMPLATE` task block in `ralph/plan.md`
2. Rename `id` to `add_market_<slug>` and update `description` with real market name
3. Set `"passes": false`
4. Run `./ralph/ralph.sh 10`

## Configuration

`config.yaml` controls the default behavior:
- `markets:` — list of market names to crawl
- `cities:` — list of cities to crawl per market
- `headless:` — run Chromium headless (default: true)
- `debug:` — save debug screenshots/HTML (default: false)
- `max_retries:` — retries per failed category (default: 2)
- `data_dir:` — output directory (default: `data/`)

CLI flags override config values.

## Output Schema

Each product observation in the JSONL output includes:
```json
{
  "market": "magnum",
  "city": "almaty",
  "category_id": "225178",
  "category_url": "...",
  "product_url": "...",
  "name": "Product Name",
  "price_current": 2650,
  "unit_raw": "/кг",
  "unit_code": "kg",
  "unit_qty": 1.0,
  "pack_qty": 150.0,
  "pack_unit": "g",
  "captured_at": "2026-03-04T...",
  "source": "listing_playwright_bs4"
}
```

Reports (`_report.json`) include:
- `summary`: counts of success/empty/failed categories
- `categories`: per-category results with item counts and durations
- `timestamps`: run start/end

## Existing Marketplaces (Implemented)

| Market | URL | Type | Categories | Notes |
|--------|-----|------|------------|-------|
| **arbuz** | arbuz.kz | Vue SPA | 40+ | Original; uses hash-based pagination |
| **vprestige** | vprestige.kz | JS-rendered | 20+ | — |
| **magnum** | magnum.kz | Strapi API | 18 | No browser needed; uses `requests` + JSON API |
| **technodom** | technodom.kz | Next.js SSR | 438 | Server-rendered; 330+ items per sample |
| **sulpak** | sulpak.kz | Server-rendered | 8 | JS object `window.insider_object.listing.items` |
| **europharma** | europharma.kz | PHP/Yii | 70 | Server-rendered; PJAX enhancement |
| **flip** | flip.kz | Server-rendered | 302 | Uses BeautifulSoup; no Playwright needed |
| **leroy_merlin** | leroymerlin.kz | React SSR | 338 | Via lemanapro.kz; requires bot-detection bypass |
| **ayanmarket** | ayanmarket.kz | REST API | 2470 | Public API at ayanmarketapi.kz; requires `x-anonymous-id` header |
| **astykzhan** | astykzhan.kz | Bitrix CMS | 335 | Server-rendered; requires city cookie for non-redirect behavior |
| **lamoda** | lamoda.kz | Nuxt SPA | 692 | SSR-rendered; requires bot-detection bypass; 403 on plain HTTP |

### Implementation Details & Troubleshooting

Each adapter logs site-specific findings in `ralph/activity.md`, including:
- **Selectors & data extraction**: CSS selectors, HTML structure, pagination patterns
- **Bot detection**: Headers, cookies, or Playwright init scripts needed
- **API endpoints**: For API-based scrapers (magnum, ayanmarket)
- **Pagination**: URL patterns, max page detection, page numbering
- **Category discovery**: How to extract category lists from each site
- **Edge cases**: Empty categories, price formatting, multi-page handling

Refer to `ralph/activity.md` entries for detailed technical notes when troubleshooting or reusing adapter patterns.

## Key Dependencies

- **beautifulsoup4** — HTML parsing (for server-rendered sites)
- **playwright** — Browser automation (Chromium headless)
- **pyyaml** — Config file parsing

Install via:
```bash
pip install -r requirements.txt
```

Then set up Playwright browsers:
```bash
playwright install chromium
```

## Development Tips

- **Find implementation patterns**: Before coding a new market, check `ralph/activity.md` for entries on similar site types (e.g., "Nuxt SPA" for lamoda, "Bitrix CMS" for astykzhan, "REST API" for ayanmarket). Implementation notes include selectors, pagination strategies, and bot-detection techniques.
- **Test single category first**: `--category-id` is useful for quick debugging before full crawls
- **Use `--no-headless`** and `--debug` together to see browser behavior and debug screenshots
- **Reuse patterns**: Similar site architectures often share markup patterns. Check existing adapters in `price_tracker/markets/` for code reuse examples (e.g., bot-detection bypass from leroy_merlin can be reused for Nuxt/Vue sites).
- **Avoid browser state**: Each category gets a fresh context; don't assume persistent state across categories
- **Handle empty categories gracefully**: Adapters return empty lists if a category has no products (not an error)
- **Document findings**: When implementing a new market, log site-specific details to `ralph/activity.md` (selectors, pagination patterns, API endpoints, headers). Future implementations benefit from these notes.

## Long-Running Agent Constraints (Ralph Loop)

When working within the Ralph Loop:
- Each task is **exactly one market**; complete all steps for that market before exiting
- Do **not** run `git init`, change remotes, or push to remote
- Do **not** rewrite existing arbuz/vprestige behavior unless required
- Keep changes **minimal and focused** on the selected task
- Always **test** with CLI commands before marking task complete
- **Log findings** to `activity.md` (selectors, pagination logic, special cases)
