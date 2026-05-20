from __future__ import annotations

import json
from pathlib import Path
from time import time

import requests

CACHE_DIR = Path("data/cache/simulation")
WORLD_BANK_URL = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicators}"
CACHE_TTL_SECONDS = 30 * 24 * 3600

WB_INDICATORS = {
    "gdp_current_usd": "NY.GDP.MKTP.CD",
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    "trade_pct_gdp": "NE.TRD.GNFS.ZS",
    "energy_imports_pct": "EG.IMP.CONS.ZS",
    "military_pct_gdp": "MS.MIL.XPND.GD.ZS",
    "inflation": "FP.CPI.TOTL.ZG",
    "population": "SP.POP.TOTL",
    "external_debt_pct_gni": "DT.DOD.DECT.GN.ZS",
}

WB_CODE_MAP = {
    "EU": "EUU",
    "TWN": "",
}


def load_country_indicator_table(country_codes: list[str]) -> dict[str, dict[str, float | str | None]]:
    wb_codes = sorted({WB_CODE_MAP.get(code, code) for code in country_codes if WB_CODE_MAP.get(code, code)})
    if not wb_codes:
        return {}
    payload = _read_world_bank_cache(wb_codes, list(WB_INDICATORS.values()))
    rows: dict[str, dict[str, float | str | None]] = {code: {} for code in country_codes}
    reverse_country = {WB_CODE_MAP.get(code, code): code for code in country_codes if WB_CODE_MAP.get(code, code)}
    reverse_indicator = {value: key for key, value in WB_INDICATORS.items()}
    for item in payload:
        country_id = item.get("countryiso3code")
        code = reverse_country.get(country_id)
        indicator_id = item.get("indicator", {}).get("id")
        key = reverse_indicator.get(indicator_id)
        if not code or not key or rows[code].get(key) is not None:
            continue
        value = item.get("value")
        if value is None:
            continue
        rows[code][key] = float(value)
        rows[code][f"{key}_year"] = item.get("date")
    return rows


def country_data_cache_health() -> tuple[Path | None, float | None, str]:
    files = list(CACHE_DIR.glob("world_bank_*.json"))
    if not files:
        return None, None, "World Bank 国家级指标尚无本地缓存，运行后会自动创建。"
    latest = max(files, key=lambda path: path.stat().st_mtime)
    age = round((time() - latest.stat().st_mtime) / 3600, 1)
    return latest, age, "World Bank 国家级指标缓存可用。"


def _read_world_bank_cache(wb_codes: list[str], indicators: list[str]) -> list[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = "_".join(wb_codes)[:120]
    path = CACHE_DIR / f"world_bank_{cache_key}.json"
    if path.exists() and time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached:
            return cached
    try:
        payload = []
        for indicator in indicators:
            payload.extend(_download_world_bank(wb_codes, [indicator]))
        if payload:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload
    except Exception:
        return []


def _download_world_bank(wb_codes: list[str], indicators: list[str]) -> list[dict]:
    url = WORLD_BANK_URL.format(countries=";".join(wb_codes), indicators=";".join(indicators))
    params = {"format": "json", "per_page": 20000, "MRV": 1}
    response = requests.get(url, params=params, timeout=8)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return []
    return payload[1]
