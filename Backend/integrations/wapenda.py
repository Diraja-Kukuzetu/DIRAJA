
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

    # Log WApenda's actual response
    if not response.ok:
        raise RuntimeError(
            f"WApenda HTTP {response.status_code}: {response.text}"
        )

    try:
        result = response.json()
    except ValueError:
        raise RuntimeError(
            f"WApenda returned an invalid JSON response: {response.text}"
        )

    if not result.get("success"):
        raise RuntimeError(
            result.get("message", "WApenda request failed")
        )

    logging.info(
        "WApenda message successfully sent to %s",
        to
    )

    return result["data"]

