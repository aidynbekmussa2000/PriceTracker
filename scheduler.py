"""
Daily scheduler for PriceTracker.
Runs the price tracker once a day at 02:00 Astana time (UTC+6).

How to use:
    python scheduler.py

To stop it: press Ctrl+C in the terminal.
"""

import subprocess
import sys
import logging
from datetime import datetime
from pathlib import Path

import schedule
import time

# ── Config ──────────────────────────────────────────────────────────────
RUN_TIME = "09:00"  # Astana local time (your PC clock)
PYTHON = str(Path(__file__).parent / ".venv" / "Scripts" / "python.exe")
PROJECT_DIR = str(Path(__file__).parent)

# ── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),                          # print to terminal
        logging.FileHandler(                              # also save to file
            Path(__file__).parent / "scheduler.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("scheduler")


def run_tracker():
    """Launch the price tracker as a subprocess."""
    log.info("=== Starting price tracker run ===")
    start = datetime.now()

    try:
        result = subprocess.run(
            [PYTHON, "-m", "price_tracker.main"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=7200,  # 2-hour safety timeout
        )
        duration = datetime.now() - start
        log.info("Finished in %s  (exit code %d)", duration, result.returncode)

        if result.stdout:
            log.info("STDOUT:\n%s", result.stdout[-2000:])  # last 2000 chars
        if result.stderr:
            log.warning("STDERR:\n%s", result.stderr[-2000:])

    except subprocess.TimeoutExpired:
        log.error("Run timed out after 2 hours!")
    except Exception as e:
        log.error("Error running tracker: %s", e)


# ── Schedule ────────────────────────────────────────────────────────────
schedule.every().day.at(RUN_TIME).do(run_tracker)

if __name__ == "__main__":
    log.info("Scheduler started. Will run daily at %s.", RUN_TIME)
    log.info("Next run: %s", schedule.next_run())
    log.info("Press Ctrl+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # check every 30 seconds
    except KeyboardInterrupt:
        log.info("Scheduler stopped by user.")
