import os
import re
from datetime import datetime, timedelta

import requests
from flask import current_app
from flask_restful import Resource
from sqlalchemy import exists

from app import db
from Server.Models.Users import Users
from Server.Models.ShopReport import ShopReport
from Server.Models.Shops import Shops

import logging
from dotenv import load_dotenv

load_dotenv()


def now_eat():
    """Current East Africa Time (UTC+3), naive."""
    return datetime.utcnow() + timedelta(hours=3)


def normalize_phone(phone, default_country_code="+254"):
    """
    Normalize a phone number to E.164.

    Handles:
      0712345678      -> +254712345678
      712345678       -> +254712345678
      +254712345678   -> +254712345678
      254712345678    -> +254712345678
      +254 712 345 678 -> +254712345678
    """
    if not phone:
        return ""

    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)

    if not digits:
        return ""

    if raw.startswith("+"):
        return "+" + digits

    if digits.startswith(default_country_code.lstrip("+")):
        return "+" + digits

    if digits.startswith("0"):
        return default_country_code + digits[1:]

    return default_country_code + digits


def get_manager_recipients(exclude_phones=None):
    """
    Return a deduplicated list of E.164 phone numbers for all
    active managers with a phone_number set.

    Optionally excludes specific normalized phone strings
    (e.g. the legacy WAPENDA_ALERT_PHONE so we don't send twice).
    """
    exclude = set(exclude_phones or [])

    rows = Users.query.filter(
        Users.role == "manager",
        Users.status == "active",
        Users.phone_number.isnot(None),
        Users.phone_number != "",
    ).all()

    recipients = []
    seen = set(exclude)

    for user in rows:
        normalized = normalize_phone(user.phone_number)
        if normalized and normalized not in seen:
            seen.add(normalized)
            recipients.append(normalized)

    return recipients


def get_shops_not_opened_today():
    """Active shops without an opening report for today."""

    today = now_eat().date()
    start_of_day = datetime.combine(today, datetime.min.time())
    end_of_day = start_of_day + timedelta(days=1)

    report_exists = (
        db.session.query(ShopReport.id)
        .filter(
            ShopReport.shop_id == Shops.shops_id,
            ShopReport.reported_at >= start_of_day,
            ShopReport.reported_at < end_of_day,
        )
        .exists()
    )

    return (
        Shops.query
        .filter(
            Shops.shopstatus == "active",
            ~report_exists,
        )
        .order_by(Shops.shopname.asc())
        .all()
    )


def send_wapenda_message(phone, message):
    """Send a WhatsApp message through WApenda."""

    api_key = os.getenv("WAPENDA_API_KEY")
    base_url = os.getenv(
        "WAPENDA_BASE_URL",
        "https://tekservix.com/wapenda/api",
    )

    if not api_key:
        raise RuntimeError("WAPENDA_API_KEY is not configured")

    response = requests.post(
        f"{base_url.rstrip('/')}/send-message",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "to": phone,
            "text": message,
        },
        timeout=20,
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(
            result.get("message", "WApenda request failed")
        )

    return result.get("data", {})


class ShopsNotOpenedToday(Resource):
    """List active shops without today's opening report."""

    def get(self):
        try:
            shops = get_shops_not_opened_today()

            return {
                "success": True,
                "date": now_eat().date().isoformat(),
                "count": len(shops),
                "shops": [
                    {
                        "shop_id": shop.shops_id,
                        "shop_name": shop.shopname,
                        "location": shop.location,
                    }
                    for shop in shops
                ],
            }, 200

        except Exception:
            current_app.logger.exception(
                "Failed to retrieve shop opening status"
            )

            return {
                "success": False,
                "message": "Failed to retrieve shop opening status",
            }, 500


class NotifyShopsNotOpenedToday(Resource):
    """
    Send today's unopened-shop report via WhatsApp to:
      - WAPENDA_ALERT_PHONE (legacy, if configured)
      - All active managers with a phone_number in Users
    """

    def post(self):
        try:
            today = now_eat().date()
            shops = get_shops_not_opened_today()

            # ── Build the message (same as before) ──
            if not shops:
                message = (
                    f"DIRAJA SHOP OPENING REPORT - "
                    f"{today:%d/%m/%Y}\n\n"
                    "All active shops have submitted their "
                    "opening reports for today."
                )
            else:
                shop_lines = [
                    f"{index}. {shop.shopname} ({shop.location})"
                    for index, shop in enumerate(shops, start=1)
                ]

                message = (
                    f"DIRAJA: SHOPS NOT OPENED - "
                    f"{today:%d/%m/%Y}\n\n"
                    f"{len(shops)} active shop(s) have not "
                    "submitted an opening report today:\n\n"
                    + "\n".join(shop_lines)
                    + "\n\nPlease follow up with the "
                    "responsible clerks."
                )

            # ── Build the recipient list ──
            # Start with the legacy alert phone (if set), then add
            # all active managers from Users, deduplicating numbers.
            recipients = []

            legacy_phone_raw = os.getenv("WAPENDA_ALERT_PHONE")
            legacy_phone = normalize_phone(legacy_phone_raw) if legacy_phone_raw else ""

            if legacy_phone:
                recipients.append(legacy_phone)

            manager_recipients = get_manager_recipients(
                exclude_phones=[legacy_phone] if legacy_phone else None
            )
            recipients.extend(manager_recipients)

            # ── No recipients at all? ──
            if not recipients:
                return {
                    "success": False,
                    "message": (
                        "No recipients available: "
                        "WAPENDA_ALERT_PHONE is not set and no "
                        "active manager has a phone_number."
                    ),
                }, 500

            # ── Send to each recipient ──
            results = []
            sent_count = 0
            failed_count = 0

            for phone in recipients:
                try:
                    result = send_wapenda_message(phone, message)
                    sent_count += 1
                    results.append({
                        "phone": phone,
                        "status": "sent",
                        "data": result,
                    })
                except Exception as exc:
                    failed_count += 1
                    current_app.logger.exception(
                        "Failed to send unopened-shop report to %s",
                        phone,
                    )
                    results.append({
                        "phone": phone,
                        "status": "failed",
                        "error": str(exc),
                    })

            return {
                "success": sent_count > 0,
                "message": (
                    f"WhatsApp notification sent to "
                    f"{sent_count} recipient(s)"
                    + (f", {failed_count} failed" if failed_count else "")
                ),
                "date": today.isoformat(),
                "shops_not_reported": len(shops),
                "recipients_total": len(recipients),
                "recipients_sent": sent_count,
                "recipients_failed": failed_count,
                "results": results,
            }, 200 if sent_count > 0 else 502

        except requests.RequestException:
            current_app.logger.exception("WApenda request failed")

            return {
                "success": False,
                "message": "Could not send WhatsApp notification",
            }, 502

        except Exception:
            current_app.logger.exception(
                "Failed to send shop opening report"
            )

            return {
                "success": False,
                "message": "Failed to generate or send the report",
            }, 500


# ─────────────────────────────────────────────────────────────
# Daily sales notification (unchanged)
# ─────────────────────────────────────────────────────────────

API_URL = os.getenv("DAILY_SALES_API_URL")
ACCESS_TOKEN = os.getenv("DAILY_SALES_ACCESS_TOKEN")

logging.basicConfig(level=logging.INFO)


def run_daily_sales_notification():

    if not API_URL or not ACCESS_TOKEN:
        raise RuntimeError("Daily sales API configuration missing")

    response = requests.get(
        API_URL,
        params={
            "period": "today",
            "notification": "manager_daily",
        },
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
        },
        timeout=120,
    )

    response.raise_for_status()

    result = response.json()

    logging.info(
        "Daily sales notification endpoint executed successfully"
    )

    return result


if __name__ == "__main__":
    try:
        run_daily_sales_notification()
    except Exception:
        logging.exception("Daily sales notification failed")