# Price Tracker — Ralph Market Expansion Plan

## Overview
Use Ralph Wiggum loop to scale `price_tracker` by adding one marketplace adapter per iteration.

Each market must follow the adapter contract in `price_tracker/markets/base.py` and produce JSONL + report output through the existing runner/storage pipeline.

---

## Task List

```json
[
  {
    "id": "baseline_context",
    "category": "setup",
    "description": "Confirm baseline architecture and existing adapters (arbuz, vprestige)",
    "steps": [
      "Read price_tracker/markets/base.py, arbuz.py, vprestige.py",
      "Confirm registration path via price_tracker/markets/__init__.py and core/runner.py",
      "Confirm current markets in config.yaml"
    ],
    "depends_on": [],
    "passes": true
  },
  {
    "id": "market_template_ready",
    "category": "setup",
    "description": "Define the reusable implementation checklist for any new market",
    "steps": [
      "Create/verify checklist in ralph/PROMPT.md for adapter contract + validations",
      "Ensure one-task-per-iteration workflow is enforced",
      "Ensure loop completion condition is explicit"
    ],
    "depends_on": ["baseline_context"],
    "passes": true
  },
  {
    "id": "add_market_TEMPLATE",
    "category": "feature",
    "description": "TEMPLATE TASK — duplicate this task, replace TEMPLATE with real market slug, then set the duplicated task to false",
    "steps": [
      "Create price_tracker/markets/<market_slug>.py with BaseMarket subclass",
      "Implement discover_categories(city) for the target site",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('<market_slug>', <ClassName>)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list only if desired for default runs",
      "Run: python -m price_tracker.main --market <market_slug> --city <city> --headless",
      "Verify output files in data/<market_slug>/<city>/",
      "Append dated entry to ralph/activity.md",
      "Mark this concrete task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_magnum",
    "category": "feature",
    "description": "Add Magnum marketplace adapter (https://magnum.kz)",
    "steps": [
      "Create price_tracker/markets/magnum.py with BaseMarket subclass",
      "Implement discover_categories(city) for magnum.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('magnum', MagnumMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market magnum --city almaty --headless",
      "Verify output files in data/magnum/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_ayanmarket",
    "category": "feature",
    "description": "Add AyanMarket marketplace adapter (https://ayanmarket.kz)",
    "steps": [
      "Create price_tracker/markets/ayanmarket.py with BaseMarket subclass",
      "Implement discover_categories(city) for ayanmarket.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('ayanmarket', AyanMarketMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market ayanmarket --city almaty --headless",
      "Verify output files in data/ayanmarket/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_astykzhan",
    "category": "feature",
    "description": "Add Astykzhan marketplace adapter (https://astykzhan.kz)",
    "steps": [
      "Create price_tracker/markets/astykzhan.py with BaseMarket subclass",
      "Implement discover_categories(city) for astykzhan.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('astykzhan', AstykzhanMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market astykzhan --city almaty --headless",
      "Verify output files in data/astykzhan/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_technodom",
    "category": "feature",
    "description": "Add Technodom marketplace adapter (https://technodom.kz)",
    "steps": [
      "Create price_tracker/markets/technodom.py with BaseMarket subclass",
      "Implement discover_categories(city) for technodom.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('technodom', TechnodomMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market technodom --city almaty --headless",
      "Verify output files in data/technodom/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_sulpak",
    "category": "feature",
    "description": "Add Sulpak marketplace adapter (https://sulpak.kz)",
    "steps": [
      "Create price_tracker/markets/sulpak.py with BaseMarket subclass",
      "Implement discover_categories(city) for sulpak.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('sulpak', SulpakMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market sulpak --city almaty --headless",
      "Verify output files in data/sulpak/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_europharma",
    "category": "feature",
    "description": "Add Europharma marketplace adapter (https://europharma.kz)",
    "steps": [
      "Create price_tracker/markets/europharma.py with BaseMarket subclass",
      "Implement discover_categories(city) for europharma.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('europharma', EuropharmaMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market europharma --city almaty --headless",
      "Verify output files in data/europharma/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_lamoda",
    "category": "feature",
    "description": "Add Lamoda marketplace adapter (https://lamoda.kz)",
    "steps": [
      "Create price_tracker/markets/lamoda.py with BaseMarket subclass",
      "Implement discover_categories(city) for lamoda.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('lamoda', LamodaMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market lamoda --city almaty --headless",
      "Verify output files in data/lamoda/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_wildberries",
    "category": "feature",
    "description": "Add Wildberries marketplace adapter (https://wildberries.kz)",
    "steps": [
      "Create price_tracker/markets/wildberries.py with BaseMarket subclass",
      "Implement discover_categories(city) for wildberries.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('wildberries', WildberriesMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market wildberries --city almaty --headless",
      "Verify output files in data/wildberries/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": false
  },
  {
    "id": "add_market_flip",
    "category": "feature",
    "description": "Add Flip marketplace adapter (https://flip.kz)",
    "steps": [
      "Create price_tracker/markets/flip.py with BaseMarket subclass",
      "Implement discover_categories(city) for flip.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('flip', FlipMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market flip --city almaty --headless",
      "Verify output files in data/flip/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  },
  {
    "id": "add_market_leroy_merlin",
    "category": "feature",
    "description": "Add Leroy Merlin marketplace adapter (https://lemanapro.kz/)",
    "steps": [
      "Create price_tracker/markets/leroy_merlin.py with BaseMarket subclass",
      "Implement discover_categories(city) for leroymerlin.kz",
      "Implement crawl_category(category, city, run_id) with pagination and parsing",
      "Register market via register_market('leroy_merlin', LeroyMerlinMarket)",
      "Import module in price_tracker/markets/__init__.py",
      "Add market slug to config.yaml markets list",
      "Run: python -m price_tracker.main --market leroy_merlin --city almaty --headless",
      "Verify output files in data/leroy_merlin/almaty/",
      "Append dated entry to ralph/activity.md",
      "Mark this task passes=true"
    ],
    "depends_on": ["market_template_ready"],
    "passes": true
  }
]
```

---

## How To Enqueue A New Market

1. Duplicate `add_market_TEMPLATE` inside the JSON list.
2. Rename ID to `add_market_<slug>` and update description/steps with real slug + city.
3. Set that new task to `"passes": false`.
4. Keep `add_market_TEMPLATE` unchanged as reusable blueprint.

---

## Agent Instructions

1. Read `ralph/activity.md` first.
2. Find the first task where `"passes": false` and all `depends_on` tasks are `true`.
3. Immediately set that task to `"passes": "in_progress"`.
4. Complete exactly that one task.
5. Run the verification command(s) in task steps.
6. Update task to `"passes": true` only after verification.
7. Append a dated log entry to `ralph/activity.md`.
8. Create one git commit for that task only.
9. Stop iteration.

## Completion Criteria
All non-template tasks in the JSON list are marked `"passes": true`.
