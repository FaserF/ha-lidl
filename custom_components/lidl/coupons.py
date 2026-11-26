"""Lidl Plus coupon fetching, filtering, activation, and deactivation helpers."""

from __future__ import annotations

import logging
from typing import Any

from curl_cffi import requests

_LOGGER = logging.getLogger(__name__)

APP_VERSION = "17.0.5"
_TIMEOUT_SECONDS = 15


def build_coupon_headers(
    access_token: str,
    country: str,
    language: str,
    store_key: str,
    segments: str = "",
) -> dict[str, str]:
    """Build scoped Lidl Plus API request headers."""
    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "Country": country,
        "Accept-Language": language,
        "store-id": store_key,
        "action-location": "app_couponslist",
        "App-Version": APP_VERSION,
        "Operating-System": "Android",
        "App": "com.lidlplus.app",
    }
    if segments:
        headers["Segment-ids"] = segments
    return headers


def fetch_user_segments(access_token: str, country: str) -> str:
    """Fetch user segment IDs for segmented promotions."""
    try:
        resp = requests.get(
            f"https://segments.lidlplus.com/api/v1/usersegments/{country}",
            headers={"Authorization": f"Bearer {access_token}"},
            impersonate="chrome110",
            timeout=10,
        )
        if resp.status_code == 200:
            segments = resp.json()
            if isinstance(segments, list):
                return ",".join(str(s) for s in segments if s is not None)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Failed to fetch Lidl Plus user segments: %s", exc)
    return ""


def is_coupon_for_store(
    coupon: dict[str, Any],
    sec_name: str,
    is_online: bool,
    store_key: str,
    store_name: str | None = None,
    store_city: str | None = None,
) -> tuple[bool, list[str]]:
    """Return whether coupon matches the local store and extracted store IDs."""
    raw_stores = (
        coupon.get("stores")
        or coupon.get("storeIds")
        or coupon.get("storeKeys")
        or coupon.get("storeList")
        or []
    )
    store_ids: list[str] = []
    if isinstance(raw_stores, list):
        for st in raw_stores:
            if isinstance(st, dict):
                s_val = st.get("id") or st.get("storeId") or st.get("key")
            else:
                s_val = st
            if s_val:
                store_ids.append(str(s_val).strip())

    is_store_match = (not store_ids) or (store_key in store_ids)

    if is_online:
        return True, store_ids

    if store_ids and not is_store_match:
        return False, store_ids

    sec_lower = sec_name.lower()
    if sec_lower in (
        "allstores",
        "onlineshop",
        "online",
        "promotions",
        "personalizedsection",
        "storecoupons",
    ):
        return True, store_ids

    if sec_name in (store_name, store_key, store_city):
        return True, store_ids

    return False, store_ids


def is_coupon_activatable(
    coupon: dict[str, Any],
    is_special: bool,
    skip_special_coupons: bool,
) -> bool:
    """Return True if a coupon is eligible for activation."""
    if bool(coupon.get("isActivated", False) or coupon.get("activated", False)):
        return False

    avail = coupon.get("availability", {})
    if isinstance(avail, dict):
        if avail.get("apologizeStatus", False):
            return False
        if avail.get("isActivatable") is False:
            return False

    if coupon.get("apologizeStatus", False):
        return False
    if coupon.get("isLocked", False) or coupon.get("locked", False):
        return False
    if coupon.get("isCombinable") is False:
        return False
    if is_special and skip_special_coupons:
        return False

    return True


def _extract_dates(coupon: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract YYYY-MM-DD start and end dates from a coupon payload."""
    validity = coupon.get("validity", {})
    start_raw = (
        validity.get("start")
        if isinstance(validity, dict)
        else (coupon.get("startValidityDate") or coupon.get("startDate"))
    )
    if not start_raw:
        start_raw = coupon.get("startValidityDate") or coupon.get("startDate")

    end_raw = (
        validity.get("end")
        if isinstance(validity, dict)
        else (coupon.get("endValidityDate") or coupon.get("endDate"))
    )
    if not end_raw:
        end_raw = coupon.get("endValidityDate") or coupon.get("endDate")

    start_date = str(start_raw)[:10] if start_raw else None
    end_date = str(end_raw)[:10] if end_raw else None
    return start_date, end_date


def _parse_coupon_metadata(
    coupon: dict[str, Any], sec_name: str
) -> tuple[bool, bool, str, str | None, str | None, str | None]:
    """Extract normalized display and flag fields for a raw coupon dict."""
    discount_info = coupon.get("discount", {})
    discount_val = (
        discount_info.get("title")
        if isinstance(discount_info, dict)
        else (discount_info or coupon.get("discountTitle") or coupon.get("offerTitle"))
    )
    desc = coupon.get("description")
    if not desc and isinstance(discount_info, dict):
        desc = discount_info.get("description")

    images = coupon.get("images")
    fallback_img = (
        images[0].get("url")
        if isinstance(images, list) and images and isinstance(images[0], dict)
        else None
    )
    image_url = coupon.get("image") or coupon.get("imageUrl") or fallback_img
    c_type = coupon.get("type") or "Standard"
    special_obj = coupon.get("specialPromotion")
    special_tag = special_obj.get("tag") if isinstance(special_obj, dict) else None
    is_online = bool(coupon.get("isOnlineShop", False)) or sec_name.lower() in (
        "onlineshop",
        "online",
    )
    is_special = bool(
        coupon.get("isSpecial", False)
        or special_tag
        or c_type in ("Special", "AssignablePromotion")
    )
    return is_online, is_special, c_type, discount_val, desc, image_url


def activate_single_coupon(
    coupon_id: str,
    headers: dict[str, str],
    country: str,
    use_legacy_v2_endpoint: bool = False,
) -> tuple[bool, int | None, str]:
    """Activate one coupon via Lidl Plus API, falling back to v1 on 404/405."""
    if use_legacy_v2_endpoint:
        urls = [
            f"https://coupons.lidlplus.com/api/v1/{country}/{coupon_id}/activation",
            f"https://coupons.lidlplus.com/app/api/v1/promotions/{coupon_id}/activation",
        ]
    else:
        urls = [
            f"https://coupons.lidlplus.com/app/api/v2/promotions/{coupon_id}/activation",
            f"https://coupons.lidlplus.com/app/api/v1/promotions/{coupon_id}/activation",
        ]

    last_status: int | None = None
    last_text = ""
    for idx, url in enumerate(urls):
        resp = requests.post(
            url,
            headers=headers,
            json={},
            impersonate="chrome110",
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code in (200, 201, 204):
            return True, resp.status_code, ""
        last_status = resp.status_code
        last_text = getattr(resp, "text", "")[:300].strip()
        if idx == 0 and resp.status_code in (404, 405):
            continue
        break
    return False, last_status, last_text


def deactivate_coupon(
    access_token: str,
    country: str,
    language: str,
    store_key: str,
    coupon_id: str,
) -> bool:
    """Deactivate a specific Lidl Plus coupon via DELETE, falling back to v1 on 404/405."""
    headers = build_coupon_headers(access_token, country, language, store_key)
    urls = [
        f"https://coupons.lidlplus.com/app/api/v2/promotions/{coupon_id}/activation",
        f"https://coupons.lidlplus.com/app/api/v1/promotions/{coupon_id}/activation",
    ]
    for idx, url in enumerate(urls):
        try:
            resp = requests.delete(
                url,
                headers=headers,
                impersonate="chrome110",
                timeout=_TIMEOUT_SECONDS,
            )
            if resp.status_code in (200, 201, 204):
                _LOGGER.info("Deactivated Lidl Plus coupon %s", coupon_id)
                return True
            if idx == 0 and resp.status_code in (404, 405):
                continue
            _LOGGER.warning(
                "Lidl rejected deactivation of coupon %s: HTTP %s %s",
                coupon_id,
                resp.status_code,
                getattr(resp, "text", "")[:300].strip(),
            )
            return False
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to deactivate coupon %s: %s", coupon_id, exc)
            return False
    return False


def _iter_sections(
    access_token: str,
    country: str,
    language: str,
    store_key: str,
    segments: str,
) -> list[tuple[dict[str, Any], bool]]:
    """Query home/logged, V2 country coupons, and V4/V1 promotionslist."""
    base_headers = build_coupon_headers(
        access_token, country, language, store_key, segments=segments
    )
    sources: list[tuple[dict[str, Any], bool]] = []

    # 1. Home Logged & Segmented promotions
    try:
        r_home = requests.post(
            f"https://home.lidlplus.com/api/v2/{country}/home/logged",
            headers=base_headers,
            json={
                "storeId": store_key,
                "modules": [{"moduleName": "promotions", "aggregateVersion": 4}],
            },
            impersonate="chrome110",
            timeout=_TIMEOUT_SECONDS,
        )
        if r_home.status_code == 200:
            home_data = r_home.json()
            promo_module = (
                home_data.get("promotions", {}) if isinstance(home_data, dict) else {}
            )
            sections = (
                promo_module.get("sections", [])
                if isinstance(promo_module, dict)
                else []
            )
            for s in sections:
                sources.append((s, False))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Failed to fetch Lidl Plus Home Logged coupons: %s", exc)

    # 2. Standard Lidl Plus Coupons (V2 API)
    try:
        r_v2 = requests.get(
            f"https://coupons.lidlplus.com/api/v2/{country}",
            headers=base_headers,
            impersonate="chrome110",
            timeout=_TIMEOUT_SECONDS,
        )
        if r_v2.status_code == 200:
            v2_data = r_v2.json()
            for s in v2_data.get("sections", []) if isinstance(v2_data, dict) else []:
                sources.append((s, True))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Failed to fetch Lidl Plus V2 coupons: %s", exc)

    # 3. Store/segment-scoped V4 promotionslist with V1 fallback
    v4_loaded = False
    try:
        r_v4 = requests.get(
            "https://coupons.lidlplus.com/app/api/v4/promotionslist",
            headers=base_headers,
            impersonate="chrome110",
            timeout=_TIMEOUT_SECONDS,
        )
        if r_v4.status_code == 200:
            v4_data = r_v4.json()
            v4_sections = (
                v4_data.get("sections", []) if isinstance(v4_data, dict) else []
            )
            if v4_sections:
                v4_loaded = True
                for s in v4_sections:
                    sources.append((s, False))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("V4 promotionslist unavailable, falling back to V1: %s", exc)

    if not v4_loaded:
        try:
            r_v1 = requests.get(
                "https://coupons.lidlplus.com/app/api/v1/promotionslist",
                headers=base_headers,
                impersonate="chrome110",
                timeout=_TIMEOUT_SECONDS,
            )
            if r_v1.status_code == 200:
                v1_data = r_v1.json()
                for s in (
                    v1_data.get("sections", []) if isinstance(v1_data, dict) else []
                ):
                    sources.append((s, False))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to fetch Lidl Plus V1 promotions: %s", exc)

    return sources


def fetch_and_process_coupons(
    access_token: str,
    country: str,
    language: str,
    store_key: str,
    store_name: str | None,
    store_city: str | None,
    today_str: str,
    auto_activate: bool,
    skip_special_coupons: bool,
    filter_local_store: bool,
) -> tuple[list[dict[str, Any]], int, int, list[dict[str, Any]]]:
    """Fetch, filter, and optionally auto-activate coupons in one unified pass."""
    segments = fetch_user_segments(access_token, country)
    headers = build_coupon_headers(
        access_token, country, language, store_key, segments=segments
    )
    sources = _iter_sections(access_token, country, language, store_key, segments)

    coupon_list: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    activated_count = 0
    failed_count = 0
    errors: list[dict[str, Any]] = []

    for section, is_legacy_v2 in sources:
        sec_name = (
            section.get("name")
            or section.get("title")
            or section.get("header")
            or "AllStores"
        )
        raw_items = list(section.get("promotions", [])) + list(
            section.get("coupons", [])
        )
        for c in raw_items:
            cid = str(c.get("id") or c.get("promotionId", "")).strip()
            if not cid or cid in seen_ids:
                continue

            avail = c.get("availability", {})
            if (
                isinstance(avail, dict) and avail.get("apologizeStatus", False)
            ) or c.get("apologizeStatus", False):
                continue

            start_date, end_date = _extract_dates(c)
            if end_date and end_date < today_str:
                continue
            if start_date and start_date > today_str:
                continue

            is_online, is_special, c_type, discount_val, desc, image_url = (
                _parse_coupon_metadata(c, sec_name)
            )
            is_store_match, store_ids = is_coupon_for_store(
                c, sec_name, is_online, store_key, store_name, store_city
            )
            if filter_local_store and not is_store_match:
                continue

            seen_ids.add(cid)
            is_act = bool(c.get("isActivated", False) or c.get("activated", False))

            if auto_activate and not is_act:
                if is_special and skip_special_coupons:
                    _LOGGER.info(
                        "Skipping special selection coupon %s based on configuration",
                        cid,
                    )
                elif not is_coupon_activatable(c, is_special, skip_special_coupons):
                    _LOGGER.debug(
                        "Skipping non-activatable coupon %s (%s)",
                        cid,
                        c.get("title"),
                    )
                else:
                    try:
                        ok, status, err_text = activate_single_coupon(
                            cid,
                            headers,
                            country,
                            use_legacy_v2_endpoint=is_legacy_v2,
                        )
                        if ok:
                            is_act = True
                            activated_count += 1
                            _LOGGER.info("Activated Lidl Plus coupon %s", cid)
                        else:
                            failed_count += 1
                            errors.append(
                                {
                                    "id": cid,
                                    "title": c.get("title"),
                                    "status": status,
                                    "error": err_text,
                                }
                            )
                            _LOGGER.warning(
                                "Lidl rejected activation of coupon %s (%s): HTTP %s %s",
                                cid,
                                c.get("title"),
                                status,
                                err_text,
                            )
                    except Exception as exc:  # noqa: BLE001
                        failed_count += 1
                        errors.append(
                            {"id": cid, "title": c.get("title"), "error": str(exc)}
                        )
                        _LOGGER.warning("Failed to activate coupon %s: %s", cid, exc)

            coupon_list.append(
                {
                    "id": cid,
                    "title": c.get("title") or c.get("name") or desc,
                    "description": desc,
                    "discount": discount_val,
                    "start_date": start_date,
                    "end_date": end_date,
                    "activated": is_act,
                    "image_url": image_url,
                    "type": c_type,
                    "section": sec_name,
                    "is_online_shop": is_online,
                    "is_special": is_special,
                    "is_local_store": is_store_match,
                    "store_ids": store_ids,
                }
            )

    return coupon_list, activated_count, failed_count, errors


def deactivate_all_coupons(
    access_token: str,
    country: str,
    language: str,
    store_key: str,
    store_name: str | None,
    store_city: str | None,
    today_str: str,
    filter_local_store: bool,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Deactivate all currently activated Lidl Plus coupons."""
    coupons, _, _, _ = fetch_and_process_coupons(
        access_token=access_token,
        country=country,
        language=language,
        store_key=store_key,
        store_name=store_name,
        store_city=store_city,
        today_str=today_str,
        auto_activate=False,
        skip_special_coupons=False,
        filter_local_store=filter_local_store,
    )
    deactivated = 0
    failed = 0
    errors: list[dict[str, Any]] = []
    for coupon in coupons:
        if not coupon.get("activated"):
            continue
        cid = str(coupon["id"])
        if deactivate_coupon(access_token, country, language, store_key, cid):
            deactivated += 1
        else:
            failed += 1
            errors.append({"id": cid, "title": coupon.get("title")})
    return deactivated, failed, errors
