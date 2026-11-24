#!/usr/bin/env python3
"""
Hit /dira/<tenant>/managerdailyprofitreport for every tenant.

cPanel cron example (once daily at 06:00 server time):
    0 6 * * * /usr/bin/python3 /home/USER/scripts/daily_profit_cron.py >> /home/USER/scripts/daily_profit_cron.log 2>&1
"""
import os
import sys
import time
import logging
import urllib.request
import urllib.error

BASE_URL = os.getenv("APP_BASE_URL", "https://app.kukuzetu.co.ke")
PATH_TEMPLATE = "/dira/{tenant}/managerdailyprofitreport"
TIMEOUT = 120

# Optional: if the endpoint enforces X-Cron-Secret, set this env var.
# If the endpoint requires nothing, leave it unset.
CRON_SECRET = os.getenv("DAILY_PROFIT_CRON_SECRET", "")

# Keep this in sync with TENANT_DATABASES in tenants.py
TENANTS = [
    "diraja",
    "shwariliving",
    "findsolgroup",
    "mageo",
    "mageoupperrunda",
    "lushvelvelt",
    "demo",
    "desgoo",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("daily_profit_cron")


def hit_tenant(tenant: str) -> bool:
    url = f"{BASE_URL}{PATH_TEMPLATE.format(tenant=tenant)}"

    req = urllib.request.Request(url, method="GET")
    if CRON_SECRET:
        req.add_header("X-Cron-Secret", CRON_SECRET)

    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
        elapsed = time.time() - t0

        if status == 200:
            log.info("OK   %-18s %s (%.1fs)", tenant, url, elapsed)
            return True

        log.error(
            "FAIL %-18s %s -> HTTP %s | %s",
            tenant, url, status, body[:300],
        )
        return False

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error(
            "FAIL %-18s %s -> HTTP %s | %s",
            tenant, url, e.code, body[:300],
        )
        return False
    except Exception as exc:
        log.exception("ERROR %-18s %s -> %s", tenant, url, exc)
        return False


def main() -> int:
    log.info("Starting daily profit report for %d tenants", len(TENANTS))

    ok, fail = 0, 0
    for tenant in TENANTS:
        if hit_tenant(tenant):
            ok += 1
        else:
            fail += 1
        time.sleep(1)  # don't hammer the app / WhatsApp provider

    log.info("Done. success=%d failed=%d total=%d", ok, fail, len(TENANTS))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())