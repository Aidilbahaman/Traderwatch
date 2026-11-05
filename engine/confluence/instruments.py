"""Instrument metadata — digits, point/pip size, asset class.

Digit/point TIDAK boleh diandaikan (spec §2.4). Jadual ini dari broker
(Exness/RoboForex) dan data sebenar kita. Sebarang symbol yang tiada di
sini dikira secara heuristik dari nilai harga, dan ditanda `is_estimated`
supaya jelas ia anggaran, bukan metadata broker sebenar.
"""

# symbol: (digits, pip_size, asset_class, base, quote)
KNOWN = {
    # --- Metal ---
    "XAUUSD": (2, 0.1, "metal", None, "USD"),
    "XAGUSD": (3, 0.001, "metal", None, "USD"),
    # --- Crypto ---
    "BTCUSD": (2, 1.0, "crypto", "BTC", "USD"),
    "ETHUSD": (2, 0.01, "crypto", "ETH", "USD"),
    "XRPUSD": (5, 0.0001, "crypto", "XRP", "USD"),
    "SOLUSD": (3, 0.01, "crypto", "SOL", "USD"),
    "DOGEUSD": (5, 0.00001, "crypto", "DOGE", "USD"),
    "ADAUSD": (5, 0.0001, "crypto", "ADA", "USD"),
    # --- Major FX ---
    "EURUSD": (5, 0.0001, "fx", "EUR", "USD"),
    "GBPUSD": (5, 0.0001, "fx", "GBP", "USD"),
    "AUDUSD": (5, 0.0001, "fx", "AUD", "USD"),
    "NZDUSD": (5, 0.0001, "fx", "NZD", "USD"),
    "USDCAD": (5, 0.0001, "fx", "USD", "CAD"),
    "USDCHF": (5, 0.0001, "fx", "USD", "CHF"),
    "USDJPY": (3, 0.01, "fx", "USD", "JPY"),
    # --- Crosses ---
    "EURGBP": (5, 0.0001, "fx", "EUR", "GBP"),
    "EURJPY": (3, 0.01, "fx", "EUR", "JPY"),
    "EURAUD": (5, 0.0001, "fx", "EUR", "AUD"),
    "EURCAD": (5, 0.0001, "fx", "EUR", "CAD"),
    "EURCHF": (5, 0.0001, "fx", "EUR", "CHF"),
    "EURNZD": (5, 0.0001, "fx", "EUR", "NZD"),
    "GBPJPY": (3, 0.01, "fx", "GBP", "JPY"),
    "GBPAUD": (5, 0.0001, "fx", "GBP", "AUD"),
    "GBPCAD": (5, 0.0001, "fx", "GBP", "CAD"),
    "GBPCHF": (5, 0.0001, "fx", "GBP", "CHF"),
    "GBPNZD": (5, 0.0001, "fx", "GBP", "NZD"),
    "AUDJPY": (3, 0.01, "fx", "AUD", "JPY"),
    "AUDCAD": (5, 0.0001, "fx", "AUD", "CAD"),
    "AUDCHF": (5, 0.0001, "fx", "AUD", "CHF"),
    "AUDNZD": (5, 0.0001, "fx", "AUD", "NZD"),
    "CADJPY": (3, 0.01, "fx", "CAD", "JPY"),
    "CADCHF": (5, 0.0001, "fx", "CAD", "CHF"),
    "CHFJPY": (3, 0.01, "fx", "CHF", "JPY"),
    "NZDJPY": (3, 0.01, "fx", "NZD", "JPY"),
    "NZDCAD": (5, 0.0001, "fx", "NZD", "CAD"),
    "NZDCHF": (5, 0.0001, "fx", "NZD", "CHF"),
}


def canonical(symbol):
    """Buang pemisah: XAU/USD -> XAUUSD."""
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())


def meta(symbol):
    """Metadata instrumen. Fallback heuristik ditanda is_estimated."""
    s = canonical(symbol)
    if s in KNOWN:
        digits, pip, cls, base, quote = KNOWN[s]
        return {"symbol": s, "digits": digits, "point_size": 10 ** -digits,
                "pip_size": pip, "asset_class": cls,
                "base_currency": base, "quote_currency": quote,
                "is_estimated": False}
    # Heuristik: JPY dalam nama -> 3 digit, lain 5. Ditanda anggaran.
    digits = 3 if s.endswith("JPY") else 5
    return {"symbol": s, "digits": digits, "point_size": 10 ** -digits,
            "pip_size": 10 ** -digits, "asset_class": "unknown",
            "base_currency": s[:3] if len(s) == 6 else None,
            "quote_currency": s[3:6] if len(s) == 6 else None,
            "is_estimated": True}


def pip_of(symbol):
    return meta(symbol)["pip_size"]


def digits_of(symbol):
    return meta(symbol)["digits"]


def format_price(symbol, value):
    """Format ikut digit instrumen — jangan andaikan 4/5 digit."""
    d = digits_of(symbol)
    if value is None:
        return "—"
    return f"{float(value):,.{d}f}"
