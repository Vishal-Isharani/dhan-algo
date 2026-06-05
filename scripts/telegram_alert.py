"""Send trading alerts via Telegram Bot API."""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _credentials() -> tuple[str, str] | None:
    load_dotenv(".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    return None


def send_alert(message: str) -> bool:
    creds = _credentials()
    if not creds:
        return False

    token, chat_id = creds
    try:
        response = requests.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        print(f"Telegram alert failed: {exc}")
        return False


def alert_success(message: str) -> bool:
    return send_alert(f"✅ {message}")


def alert_failure(message: str) -> bool:
    return send_alert(f"❌ {message}")


def alert_target(message: str) -> bool:
    return send_alert(f"🎯 TARGET\n{message}")


def alert_stop_loss(message: str) -> bool:
    return send_alert(f"🛑 STOP LOSS\n{message}")
