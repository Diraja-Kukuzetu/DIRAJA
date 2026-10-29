
import os
from datetime import datetime, timedelta

import requests
from flask import current_app
from flask_restful import Resource
from sqlalchemy import exists

from app import db
from Server.Models.ShopReport import ShopReport
from Server.Models.Shops import Shops


def now_eat():
    """Current East Africa Time (UTC+3), naive."""
    return datetime.utcnow() + timedelta(hours=3)


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
        raise RuntimeError(
            "WAPENDA_API_KEY is not configured"
        )

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
    """Send today's unopened-shop report via WhatsApp."""

    def post(self):
        try:
            phone = os.getenv("WAPENDA_ALERT_PHONE")

            if not phone:
                return {
                    "success": False,
                    "message": (
                        "WAPENDA_ALERT_PHONE is not configured"
                    ),
                }, 500

            today = now_eat().date()
            shops = get_shops_not_opened_today()

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

            result = send_wapenda_message(phone, message)

            return {
                "success": True,
                "message": "WhatsApp notification queued",
                "date": today.isoformat(),
                "shops_not_reported": len(shops),
                "whatsapp": result,
            }, 200

        except requests.RequestException:
            current_app.logger.exception(
                "WApenda request failed"
            )

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
