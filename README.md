# Price Tracker

A multi-marketplace price tracker for Kazakh e-commerce platforms. Discover product categories and scrape real-time price data from multiple online marketplaces, with normalized JSON and JSONL output.

## Table of Contents

- [Features](#features)
- [Supported Marketplaces](#supported-marketplaces)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [Basic Commands](#basic-commands)
  - [Advanced Options](#advanced-options)
  - [Configuration](#configuration)
- [Output Format](#output-format)
- [Adding New Markets](#adding-new-markets)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

## Features

- **Multi-marketplace scraping** — Track prices from 11+ Kazakh e-commerce sites simultaneously
- **Automatic category discovery** — Crawls all available product categories per market
- **Normalized output** — Standardized JSON/JSONL format across all markets
- **Flexible configuration** — YAML-based config + CLI overrides for fine-grained control
- **Retry logic** — Built-in error handling with configurable retries per category
- **Debug mode** — Capture screenshots and HTML snapshots for troubleshooting
- **Adapter pattern** — Market-agnostic architecture makes adding new markets simple

## Supported Marketplaces

| Market | Type | Categories | Notes |
|--------|------|-----------|-------|
| **arbuz.kz** | Vue SPA | 40+ | Fast food & groceries |
| **magnum.kz** | REST API | 18 | Supermarket chain |
| **technodom.kz** | Server-rendered | 438 | Electronics retailer |
| **sulpak.kz** | Server-rendered | 8 | Electronics store |
| **europharma.kz** | PHP/Yii | 70 | Pharmacy chain |
| **vprestige.kz** | JS-rendered | 20+ | Premium products |
| **flip.kz** | Server-rendered | 302 | Gadgets & electronics |
| **leroy_merlin.kz** | React SSR | 338 | Home improvement |
| **ayanmarket.kz** | REST API | 2470+ | Marketplace |
| **astykzhan.kz** | Bitrix CMS | 335 | Department store |
| **lamoda.kz** | Nuxt SPA | 692 | Fashion & apparel |

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run all markets (from config.yaml)
python -m price_tracker.main

# Run a single market + city
python -m price_tracker.main --market magnum --city almaty

# List categories without crawling
python -m price_tracker.main --list-categories --market technodom --city almaty
```

Output files are saved to `data/` in the format:
```
data/
├── magnum/
│   └── almaty/
│       ├── 2026-03-10T14-30-45Z.jsonl
│       └── 2026-03-10T14-30-45Z_report.json
├── arbuz/
│   └── almaty/
│       ├── 2026-03-10T15-12-30Z.jsonl
│       └── 2026-03-10T15-12-30Z_report.json
└── ...
```

## Installation

### Prerequisites
- Python 3.8+
- pip or uv

### Steps

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd arbuz_parsing
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers:**
   ```bash
   playwright install chromium
   ```

4. **(Optional) Use the install script:**
   ```bash
   bash install.sh
   ```

## Usage

### Basic Commands

#### Run All Markets (Default)
Crawls all markets and cities defined in `config.yaml`:
```bash
python -m price_tracker.main
```

#### Run a Specific Market + City
```bash
python -m price_tracker.main --market magnum --city almaty
python -m price_tracker.main --market sulpak --city aktau
```

#### List Categories Without Crawling
Preview all categories for a market/city without downloading data:
```bash
python -m price_tracker.main --list-categories --market technodom --city almaty
```

Output example:
```
Found 438 categories in technodom / almaty:
225178 - Молочные продукты
225179 - Хлеб и выпечка
225180 - Мясо и птица
...
```

#### Test a Single Category
Useful for debugging specific product categories:
```bash
python -m price_tracker.main --market flip --city almaty --category-id 44
```

#### View Browser Activity (No Headless Mode)
Debug by watching the browser in real-time:
```bash
python -m price_tracker.main --market europharma --city almaty --no-headless
```

#### Enable Debug Mode
Saves screenshots and HTML snapshots for each category crawled:
```bash
python -m price_tracker.main --market leroy_merlin --city almaty --debug
```

Debug files are saved to:
```
debug_{market}/
├── {category_id}_1.png          # Screenshot before crawl
├── {category_id}_1.html         # Initial HTML
├── {category_id}_2.png          # After pagination
└── {category_id}_2.html         # Final HTML
```

#### Use a Custom Config File
```bash
python -m price_tracker.main --config custom_config.yaml
```

### Advanced Options

```bash
python -m price_tracker.main --help
```

**Available flags:**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--market` | str | — | Single market to crawl (overrides config) |
| `--city` | str | — | Single city to crawl (overrides config) |
| `--category-id` | str | — | Test a single category |
| `--list-categories` | flag | False | Discover & list categories, then exit |
| `--config` | str | `config.yaml` | Path to config file |
| `--data-dir` | str | `data/` | Output directory for JSON/JSONL |
| `--no-headless` | flag | False | Show browser window (headless=false) |
| `--debug` | flag | False | Save debug screenshots/HTML |
| `--max-retries` | int | 2 | Retries per failed category |

**Example with multiple flags:**
```bash
python -m price_tracker.main \
  --market technodom \
  --city almaty \
  --data-dir ./output \
  --debug \
  --max-retries 3 \
  --no-headless
```

### Configuration

The `config.yaml` file controls default behavior:

```yaml
markets:
  - arbuz
  - magnum
  - technodom
  - sulpak
  - europharma

cities:
  - almaty
  - aktau
  - astana

headless: true      # Run Chromium in headless mode
debug: false        # Save debug screenshots/HTML
max_retries: 2      # Retries per failed category
data_dir: data/     # Output directory
```

**Priority order** (highest to lowest):
1. CLI flags (`--market arbuz --city almaty`)
2. Config file (`config.yaml`)
3. Hardcoded defaults

## 📊 Output Format

### JSONL Format (Per-Product Stream)

Each product observation is appended to a `.jsonl` file (one JSON object per line):

**File:** `data/{market}/{city}/{timestamp}Z.jsonl`

**Schema:**
```json
{
  "market": "magnum",
  "city": "almaty",
  "category_id": "225178",
  "category_url": "https://magnum.kz/almaty/groceries",
  "product_url": "https://magnum.kz/product/123456",
  "name": "Organic Whole Milk 1L",
  "price_current": 2650,
  "unit_raw": "/кг",
  "unit_code": "kg",
  "unit_qty": 1.0,
  "pack_qty": 150.0,
  "pack_unit": "g",
  "captured_at": "2026-03-10T14:30:45Z",
  "source": "listing_playwright_bs4"
}
```

**Fields:**
- `market` — Marketplace identifier (e.g., `arbuz`, `magnum`)
- `city` — City name (e.g., `almaty`, `aktau`)
- `category_id` — Category identifier on the marketplace
- `category_url` — Full URL to the category page
- `product_url` — Direct link to the product
- `name` — Product name (normalized)
- `price_current` — Current price in local currency (KZT)
- `unit_raw` — Raw unit from site (e.g., `/кг`, `/л`)
- `unit_code` — Standardized unit code (`kg`, `l`, `piece`, etc.)
- `unit_qty` — Quantity per unit
- `pack_qty` — Package quantity
- `pack_unit` — Package unit
- `captured_at` — ISO 8601 timestamp
- `source` — Data extraction method (e.g., `listing_playwright_bs4`)

### JSON Report Format

A summary report is also generated for each crawl:

**File:** `data/{market}/{city}/{timestamp}Z_report.json`

**Schema:**
```json
{
  "market": "technodom",
  "city": "almaty",
  "crawl_start": "2026-03-10T14:30:00Z",
  "crawl_end": "2026-03-10T15:45:30Z",
  "summary": {
    "total_categories": 438,
    "successful": 430,
    "empty": 5,
    "failed": 3,
    "total_products": 45230
  },
  "categories": [
    {
      "category_id": "225178",
      "name": "Молочные продукты",
      "status": "success",
      "product_count": 125,
      "duration_seconds": 12.5
    },
    {
      "category_id": "225179",
      "name": "Хлеб и выпечка",
      "status": "empty",
      "product_count": 0,
      "duration_seconds": 2.1
    },
    {
      "category_id": "225180",
      "name": "Мясо и птица",
      "status": "failed",
      "product_count": 0,
      "error": "Timeout waiting for selector",
      "duration_seconds": 30.0
    }
  ]
}
```

## 🆕 Adding New Markets

### Option 1: Manual Implementation (Full Control)

1. **Create market adapter:**
   ```bash
   touch price_tracker/markets/my_market.py
   ```

2. **Implement the `BaseMarket` contract:**
   ```python
   from price_tracker.markets.base import BaseMarket
   from price_tracker.core.models import CategoryInfo, PriceObservation

   class MyMarketAdapter(BaseMarket):
       market_name = "my_market"
       supported_cities = ["almaty", "aktau", "astana"]

       async def discover_categories(self, city):
           """Return list of CategoryInfo objects."""
           # Your implementation here
           return [
               CategoryInfo(id="1", name="Category 1", url="https://..."),
               # ...
           ]

       async def crawl_category(self, category, city, run_id):
           """Scrape products from a category. Return list of PriceObservation."""
           # Your implementation here
           return [
               PriceObservation(
                   market=self.market_name,
                   city=city,
                   category_id=category.id,
                   # ... other fields
               ),
               # ...
           ]
   ```

3. **Register the market:**
   In `price_tracker/markets/my_market.py`, add at the module level:
   ```python
   from price_tracker.core.runner import register_market
   register_market("my_market", MyMarketAdapter)
   ```

4. **Import in `__init__.py`:**
   ```python
   # price_tracker/markets/__init__.py
   from . import my_market  # This triggers the registration
   ```

5. **Add to config.yaml:**
   ```yaml
   markets:
     - my_market
     - arbuz
     - magnum
   ```

6. **Test:**
   ```bash
   python -m price_tracker.main --market my_market --city almaty --list-categories
   ```

### Option 2: Ralph Loop (Autonomous Agent)

Use the autonomous agent workflow in the `ralph/` directory for hands-off implementation:

1. **Add task to `ralph/plan.md`:**
   ```json
   {
     "id": "add_market_kaspi",
     "description": "Implement Kaspi.kz adapter",
     "passes": false
   }
   ```

2. **Run the loop:**
   ```bash
   bash -c 'unset CLAUDECODE && ./ralph/ralph.sh 10'
   ```

The agent will:
- Implement the market adapter
- Test it locally
- Commit changes
- Log findings to `ralph/activity.md`

See [CLAUDE.md](CLAUDE.md) for detailed Ralph Loop workflow.

## 🛠️ Development

### Project Structure

```
price_tracker/
├── core/
│   ├── runner.py       # Main orchestrator
│   ├── storage.py      # JSON/JSONL output
│   ├── models.py       # Data models
│   └── utils.py        # Shared utilities
├── markets/
│   ├── base.py         # BaseMarket contract
│   ├── arbuz.py        # Arbuz adapter
│   ├── magnum.py       # Magnum adapter
│   └── ...             # Other market adapters
└── main.py             # CLI entry point
```

### Architecture Overview

**Three-layer design:**

1. **Runner** (`core/runner.py`)
   - Orchestrates the crawl across all markets/cities
   - Manages a single shared Chromium browser instance
   - Handles retry logic
   - Writes output via Storage

2. **Adapters** (`markets/{market}.py`)
   - Implement `BaseMarket` interface
   - Each adapter defines:
     - `market_name` — identifier
     - `supported_cities` — available cities
     - `discover_categories(city)` — find all product categories
     - `crawl_category(category, city, run_id)` — scrape products

3. **Storage** (`core/storage.py`)
   - Writes JSONL + JSON report files
   - Organizes output by market/city/timestamp

### Key Files

- **[main.py](price_tracker/main.py)** — CLI entry point and argument parsing
- **[runner.py](price_tracker/core/runner.py)** — Main orchestrator logic
- **[base.py](price_tracker/markets/base.py)** — BaseMarket abstract class
- **[storage.py](price_tracker/core/storage.py)** — Output handling
- **[config.yaml](config.yaml)** — Default configuration

### Implementation Tips

- **Pick the right approach** — Use Playwright + BeautifulSoup for JS-rendered sites, plain `requests` for server-rendered HTML, and `requests` directly for REST APIs to reduce overhead.
- **Reuse patterns** — Check existing adapters (e.g., `markets/lamoda.py`, `markets/magnum.py`) for site-specific solutions.
- **Test single category first** — Use `--category-id` flag to debug before full crawls.
- **Check `ralph/activity.md`** — Previous agent work logs technical findings (selectors, pagination, bot detection).
- **Fresh context per category** — Each category gets a new browser context; don't assume state persists.

## 🐛 Troubleshooting

### Issue: "Timeout waiting for selector"

**Cause:** The CSS selector changed or the page structure is different.

**Solution:**
1. Run with `--no-headless --debug` to see what's happening:
   ```bash
   python -m price_tracker.main --market arbuz --city almaty --no-headless --debug
   ```
2. Check debug HTML/screenshots in `debug_arbuz/` folder
3. Update the selector in the adapter file
4. Test again with `--category-id` flag

### Issue: "403 Forbidden" or Bot Detection

**Cause:** The site is blocking automated traffic.

**Solution:**
1. Check [CLAUDE.md](CLAUDE.md) — many adapters document bot-detection workarounds
2. Check existing adapters for similar sites:
   - **leroy_merlin.py** — includes bot-detection bypass for React sites
   - **lamoda.py** — handles Nuxt SPA bot detection
   - **ayanmarket.py** — uses REST API (avoids detection)
3. Common fixes:
   - Add headers (User-Agent, Referer)
   - Use Playwright init scripts
   - Wait for specific selectors before crawling

### Issue: "No categories found"

**Cause:** Category discovery is failing.

**Solution:**
1. Check the category URL pattern in the adapter
2. Run `--list-categories --no-headless --debug` to see the page
3. Verify the CSS selectors in `discover_categories()` method
4. Update selectors if site markup changed

### Issue: Empty Output Files

**Cause:** Products aren't matching the CSS selector or the category is actually empty.

**Solution:**
1. Verify the product selector in the adapter
2. Run with `--no-headless --debug` to inspect the DOM
3. Check if pagination is working correctly
4. Some categories may legitimately be empty (not an error)

### Issue: Out of Memory or Slow Performance

**Cause:** Too many categories or pages per category.

**Solution:**
1. Reduce concurrent crawls (not parallelized, but can add in future)
2. Use `--category-id` to test individual categories
3. Reduce `max_retries` to speed up failed categories
4. Check for pagination bugs (infinite loop)

### Debug Workflow

For any issue, follow this debug workflow:

```bash
# 1. Start with the failing market + city
python -m price_tracker.main --market <market> --city <city> --list-categories

# 2. Pick a category that's failing
python -m price_tracker.main \
  --market <market> \
  --city <city> \
  --category-id <id> \
  --debug \
  --no-headless

# 3. Inspect debug files
ls debug_<market>/

# 4. Check the adapter code
vim price_tracker/markets/<market>.py

# 5. Fix and re-test
python -m price_tracker.main \
  --market <market> \
  --city <city> \
  --category-id <id>
```

## Requirements

- **beautifulsoup4** — HTML parsing
- **playwright** — Browser automation
- **pyyaml** — YAML config parsing
- **requests** — HTTP client (for REST APIs and server-rendered sites)

Install all at once:
```bash
pip install -r requirements.txt
playwright install chromium
```


**Last updated:** March 2026
**Maintained by:** Development Team
