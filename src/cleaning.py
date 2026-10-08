import pandas as pd

CURRENCY_MAP = {
    "USD": "USD", "US$": "USD", "$": "USD",
    "EUR": "EUR", "€": "EUR",
    "GBP": "GBP", "£": "GBP",
    "ZAR": "ZAR", "R": "ZAR",
}

CHANNEL_MAP = {
    "direct": "direct",
    "ota": "ota",
    "o.t.a": "ota",
    "website": "website",
    "travel agent": "travel_agent",
}

COUNTRY_MAP = {"S. Africa": "South Africa"}


def parse_mixed_datetime(series):
    """Parse the mixed source date formats without row-by-row Python loops."""
    cleaned = series.astype("string").str.strip()
    try:
        return pd.to_datetime(cleaned, format="mixed", dayfirst=True, errors="coerce")
    except TypeError:  # compatibility with older pandas
        return pd.to_datetime(cleaned, dayfirst=True, errors="coerce")


def clean_bookings(df):
    out = df.copy()
    text_cols = ["booking_id", "property_id", "booking_status"]
    for col in text_cols:
        out[col] = out[col].astype("string").str.strip()

    for col in ["check_in", "check_out", "created_at", "updated_at"]:
        out[col] = parse_mixed_datetime(out[col])

    for col in ["num_guests", "room_rate", "revenue"]:
        cleaned = out[col].astype("string").str.replace(",", "", regex=False).str.strip()
        out[col] = pd.to_numeric(cleaned, errors="coerce")

    raw_currency = out["currency"].astype("string").str.strip().str.upper()
    out["currency"] = raw_currency.map(CURRENCY_MAP).fillna(raw_currency)

    channel = (out["booking_channel"].astype("string").str.strip().str.lower()
               .str.replace(r"\s+", " ", regex=True))
    out["booking_channel"] = channel.map(CHANNEL_MAP).fillna(channel)
    out["booking_status"] = out["booking_status"].str.lower()
    return out


def clean_properties(df):
    out = df.copy()
    for col in ["property_id", "property_name", "country", "region", "property_status"]:
        out[col] = out[col].astype("string").str.strip()
    out["country"] = out["country"].replace(COUNTRY_MAP)
    return out


def clean_fx(df):
    out = df.copy()
    out["currency"] = out["currency"].astype("string").str.strip().str.upper()
    out["effective_from"] = pd.to_datetime(out["effective_from"], errors="coerce")
    out["rate_to_zar"] = pd.to_numeric(out["rate_to_zar"], errors="coerce")
    return out.sort_values(["currency", "effective_from"])
