
import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv(
    "WAPENDA_BASE_URL",
    "https://tekservix.com/wapenda/api",
)

API_KEY = os.getenv("WAPENDA_API_KEY")


def send_whatsapp_message(to: str, text: str) -> dict:
    """Send a WhatsApp text message through WApenda."""

    if not API_KEY:
        raise RuntimeError("WAPENDA_API_KEY is not configured")

    if not to or not text:
        raise ValueError("Recipient and message are required")

    response = requests.post(
        f"{BASE_URL}/send-message",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "to": to,
            "text": text,
        },
        timeout=20,
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(
            result.get("message", "WApenda request failed")
        )

    return result["data"]
