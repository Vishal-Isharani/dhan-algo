"""Check and whitelist the current IP for Dhan order APIs."""

from __future__ import annotations

import os
from typing import Any

import requests
from dhanhq import DhanLogin
from dotenv import load_dotenv

from scripts.dhan_helpers import get_access_token, is_invalid_token_error, unwrap_sdk_data


def get_public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=10).text.strip()
    except Exception:
        return "unknown"


def _get_ip_status(client_id: str, access_token: str) -> dict[str, Any]:
    login = DhanLogin(client_id)
    response = login.get_ip(access_token)
    return unwrap_sdk_data(response)


def _ip_already_listed(ip: str, status: dict[str, Any]) -> bool:
    listed = {status.get("primaryIP"), status.get("secondaryIP")}
    return ip in {value for value in listed if value}


def _pick_whitelist_action(ip: str, status: dict[str, Any]) -> tuple[str, str] | None:
    primary = status.get("primaryIP") or ""
    secondary = status.get("secondaryIP") or ""

    if ip == primary or ip == secondary:
        return None

    if not primary:
        return "set", "PRIMARY"
    if not secondary:
        return "set", "SECONDARY"

    return "modify", "PRIMARY"


def _api_succeeded(response: dict[str, Any]) -> tuple[bool, str]:
    if response.get("status") != "success":
        return False, str(response.get("remarks") or response)

    payload = response.get("data")
    if isinstance(payload, dict):
        if payload.get("status") == "ERROR":
            return False, str(payload.get("message") or payload)
        if payload.get("status") == "success":
            return True, str(payload.get("message") or "OK")
    return True, "OK"


def _whitelist_ip(
    client_id: str,
    access_token: str,
    ip: str,
    action: str,
    ip_flag: str,
) -> tuple[bool, str]:
    login = DhanLogin(client_id)
    if action == "set":
        response = login.set_ip(access_token, ip, ip_flag, client_id)
    else:
        response = login.modify_ip(access_token, ip, ip_flag, client_id)
    return _api_succeeded(response)


def _format_ip_status(status: dict[str, Any], public_ip: str) -> str:
    return (
        f"Detected IP:  {status.get('detectedIP', public_ip)}\n"
        f"Primary IP:   {status.get('primaryIP') or '(not set)'}\n"
        f"Secondary IP: {status.get('secondaryIP') or '(not set)'}\n"
        f"Match status: {status.get('ipMatchStatus')}\n"
        f"Orders allowed: {status.get('ordersAllowed')}"
    )


def ensure_ip_whitelisted() -> bool:
    """Return True when Dhan order APIs are allowed from the current IP."""

    load_dotenv(".env")
    client_id = os.environ.get("DHAN_CLIENT_ID")
    if not client_id:
        raise ValueError("DHAN_CLIENT_ID must be set in .env")

    public_ip = get_public_ip()
    status = None
    for attempt, force_refresh in enumerate((False, True)):
        access_token = get_access_token(force_refresh=force_refresh)
        try:
            status = _get_ip_status(client_id, access_token)
            break
        except ValueError as exc:
            if is_invalid_token_error(exc) and attempt == 0:
                print("Access token expired — refreshing via PIN+TOTP...")
                continue
            raise

    if status is None:
        return False

    if status.get("ordersAllowed"):
        detected = status.get("detectedIP", public_ip)
        match = status.get("ipMatchStatus", "OK")
        print(f"IP OK: {detected} ({match})")
        return True

    ip_to_whitelist = status.get("detectedIP") or public_ip
    if ip_to_whitelist in ("unknown", "", None):
        print("WARNING: Could not detect current public IP.")
        print(_format_ip_status(status, public_ip))
        return False

    print("WARNING: Current IP is not whitelisted for Dhan order APIs.")
    print(_format_ip_status(status, public_ip))

    if _ip_already_listed(ip_to_whitelist, status):
        print("IP is already saved on Dhan but does not match the active connection.")
        return False

    action_plan = _pick_whitelist_action(ip_to_whitelist, status)
    if action_plan is None:
        return bool(status.get("ordersAllowed"))

    attempts: list[tuple[str, str]] = [action_plan]
    if action_plan == ("modify", "PRIMARY"):
        attempts.append(("modify", "SECONDARY"))

    whitelisted = False
    last_error = ""

    for action, ip_flag in attempts:
        print(f"Trying to whitelist {ip_to_whitelist} as {ip_flag} ({action})...")
        try:
            ok, message = _whitelist_ip(client_id, access_token, ip_to_whitelist, action, ip_flag)
        except Exception as exc:
            last_error = str(exc)
            print(f"Whitelist request failed: {exc}")
            continue

        if ok:
            print(f"Whitelisted {ip_to_whitelist} as {ip_flag}.")
            whitelisted = True
            break

        last_error = message
        print(f"Whitelist failed: {message}")

    if not whitelisted:
        if "6 days" in last_error or "7 days" in last_error:
            print("Note: Dhan only allows IP changes once every 7 days.")
        return False

    status = _get_ip_status(client_id, get_access_token())
    if status.get("ordersAllowed"):
        print(f"IP OK: {status.get('detectedIP', ip_to_whitelist)}")
        return True

    print("IP saved, but orders are still not allowed from this connection.")
    print(_format_ip_status(status, public_ip))
    return False
