#!/usr/bin/env python3
"""
market_data_official.py

Template module to integrate official index feeds (JPX / QUICK / vendor). This file provides a
simple interface `fetch_price(symbol_key)` that returns a dict {price, source, raw} or None on failure.

Notes:
- You must have an account / contract with JPX (or another vendor) and set environment variables
  with credentials. This module is a template and will need vendor-specific endpoints/params.
"""
import os
import json
import time
from typing import Optional, Dict, Any

try:
    import requests
except Exception:
    requests = None

# Mapping logical symbol keys to provider symbols / codes
DEFAULT_SYMBOL_MAP = {
    'JP225': os.getenv('OFFICIAL_SYMBOL_JP225', 'N225'),
    'DE40': os.getenv('OFFICIAL_SYMBOL_DE40', 'DE40'),
    'NASDAQ_MINI': os.getenv('OFFICIAL_SYMBOL_NASDAQ_MINI', 'NQF'),
    'AAPL': os.getenv('OFFICIAL_SYMBOL_AAPL', 'AAPL'),
    'MSFT': os.getenv('OFFICIAL_SYMBOL_MSFT', 'MSFT'),
    'GOLD_SPOT': os.getenv('OFFICIAL_SYMBOL_GOLD', 'XAU')
}


def _get_api_config() -> Dict[str, str]:
    """Read API configuration from env vars. Example vars:
    JPX_API_URL, JPX_API_KEY, JPX_API_SECRET (vendor dependent)
    """
    return {
        'url': os.getenv('JPX_API_URL') or os.getenv('OFFICIAL_API_URL', ''),
        'key': os.getenv('JPX_API_KEY') or os.getenv('OFFICIAL_API_KEY', ''),
        'secret': os.getenv('JPX_API_SECRET') or os.getenv('OFFICIAL_API_SECRET', '')
    }


def fetch_price(symbol_key: str) -> Optional[Dict[str, Any]]:
    """Fetch price for a logical symbol key using the official vendor API.

    Returns: {'price': float, 'source': 'jpx', 'raw': {...}} or None if not available.
    """
    cfg = _get_api_config()
    url = cfg.get('url')
    api_key = cfg.get('key')

    provider_symbol = DEFAULT_SYMBOL_MAP.get(symbol_key)
    if not provider_symbol:
        return None

    # If requests is not available or no API URL configured, return None (template mode)
    if not requests or not url or not api_key:
        return None

    try:
        # Vendor-specific request - placeholder example for a JSON REST API
        params = {'symbol': provider_symbol, 'apikey': api_key}
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        # The parsing below depends on vendor response format; adjust accordingly.
        # Example: {'symbol':'N225','price':51497.2,'ts':...}
        if 'price' in data:
            return {'price': float(data['price']), 'source': 'official', 'raw': data}
        # try common keys
        if 'last' in data:
            return {'price': float(data['last']), 'source': 'official', 'raw': data}
    except Exception:
        return None

    return None


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: market_data_official.py SYMBOL_KEY')
        sys.exit(2)
    out = fetch_price(sys.argv[1])
    print(json.dumps(out or {}, indent=2, ensure_ascii=False))
