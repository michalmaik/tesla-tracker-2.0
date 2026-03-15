import json
import time
import re
import os
from datetime import datetime, timezone
from curl_cffi import requests as cf_requests
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"
HISTORY_FILE = "price_history.json"

API_URL = "https://ev-inventory.com/lib/get_stock_23.php"

LISTING_TYPES = [
    {"token": "131076", "label": "CPO"},
]

COUNTRIES = [
    {"name": "Netherlands",    "currency": "EUR"},
    {"name": "Germany",        "currency": "EUR"},
    {"name": "France",         "currency": "EUR"},
    {"name": "Belgium",        "currency": "EUR"},
    {"name": "Luxembourg",     "currency": "EUR"},
    {"name": "Austria",        "currency": "EUR"},
    {"name": "Spain",          "currency": "EUR"},
    {"name": "Portugal",       "currency": "EUR"},
    {"name": "Italy",          "currency": "EUR"},
    {"name": "Greece",         "currency": "EUR"},
    {"name": "Ireland",        "currency": "EUR"},
    {"name": "Finland",        "currency": "EUR"},
    {"name": "Estonia",        "currency": "EUR"},
    {"name": "Latvia",         "currency": "EUR"},
    {"name": "Lithuania",      "currency": "EUR"},
    {"name": "Slovakia",       "currency": "EUR"},
    {"name": "Slovenia",       "currency": "EUR"},
    {"name": "Malta",          "currency": "EUR"},
    {"name": "Cyprus",         "currency": "EUR"},
    {"name": "Croatia",        "currency": "EUR"},
    {"name": "Sweden",         "currency": "SEK"},
    {"name": "Denmark",        "currency": "DKK"},
    {"name": "Poland",         "currency": "PLN"},
    {"name": "Czech Republic", "currency": "CZK"},
    {"name": "Hungary",        "currency": "HUF"},
    {"name": "Romania",        "currency": "RON"},
    {"name": "Bulgaria",       "currency": "BGN"},
]

COUNTRY_FLAGS = {
    "Netherlands": "🇳🇱", "Germany": "🇩🇪", "France": "🇫🇷",
    "Belgium": "🇧🇪", "Luxembourg": "🇱🇺", "Sweden": "🇸🇪",
    "Denmark": "🇩🇰", "Austria": "🇦🇹", "Spain": "🇪🇸",
    "Portugal": "🇵🇹", "Italy": "🇮🇹", "Greece": "🇬🇷",
    "Ireland": "🇮🇪", "Finland": "🇫🇮", "Estonia": "🇪🇪",
    "Latvia": "🇱🇻", "Lithuania": "🇱🇹", "Slovakia": "🇸🇰",
    "Slovenia": "🇸🇮", "Malta": "🇲🇹", "Cyprus": "🇨🇾",
    "Poland": "🇵🇱", "Czech Republic": "🇨🇿", "Hungary": "🇭🇺",
    "Romania": "🇷🇴", "Bulgaria": "🇧🇬", "Croatia": "🇭🇷",
}


COUNTRY_LOCALE = {
    "Netherlands": "nl_NL", "Germany": "de_DE", "France": "fr_FR",
    "Belgium": "fr_BE", "Luxembourg": "fr_LU", "Sweden": "sv_SE",
    "Denmark": "da_DK", "Austria": "de_AT", "Spain": "es_ES",
    "Portugal": "pt_PT", "Italy": "it_IT", "Greece": "el_GR",
    "Ireland": "en_IE", "Finland": "fi_FI", "Estonia": "et_EE",
    "Latvia": "lv_LV", "Lithuania": "lt_LT", "Slovakia": "sk_SK",
    "Slovenia": "sl_SI", "Malta": "en_MT", "Cyprus": "el_CY",
    "Poland": "pl_PL", "Czech Republic": "cs_CZ", "Hungary": "hu_HU",
    "Romania": "ro_RO", "Bulgaria": "bg_BG", "Croatia": "hr_HR",
}

MAX_EUR   = 19500
MIN_YEAR_CPO  = 2018
MIN_YEAR_USED = 2018
MAX_YEAR  = 2021
MAX_KM    = 200000

HEADERS = {
    "accept": "*/*",
    "accept-language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://ev-inventory.com",
    "referer": "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}


def get_exchange_rates():
    try:
        resp = requests.get("https://api.frankfurter.app/latest?from=PLN&to=EUR,SEK,DKK,CZK,HUF,RON,BGN", timeout=10)
        data = resp.json()
        result = {c: 1.0 / r for c, r in data.get("rates", {}).items()}
        result["PLN"] = 1.0
        if not result.get("BGN") or result["BGN"] == 0:
            result["BGN"] = result.get("EUR", 4.25) / 1.956
        print(f"  Kursy: EUR={result.get('EUR',0):.2f} SEK={result.get('SEK',0):.4f} DKK={result.get('DKK',0):.4f}")
        return result
    except Exception as e:
        print(f"  Błąd kursów: {e}, używam przybliżonych")
        return {"EUR": 4.25, "SEK": 0.40, "DKK": 0.57, "CZK": 0.17, "HUF": 0.011, "RON": 0.85, "BGN": 2.17, "PLN": 1.0}


def to_eur(price, currency, rates):
    if currency == "EUR":
        return price
    return price * rates.get(currency, 1.0) / rates.get("EUR", 4.25)


def to_pln(price, currency, rates):
    return price * rates.get(currency, 1.0)


def get_max_local(currency, rates):
    if currency == "EUR":
        return MAX_EUR
    return int(MAX_EUR * rates.get("EUR", 4.25) / rates.get(currency, 1.0))


def get_currency_for_country(country):
    for c in COUNTRIES:
        if c["name"] == country:
            return c["currency"]
    return "EUR"



def tesla_url(car):
    """Buduje bezpośredni link do strony auta na tesla.com"""
    country = car.get("country", "")
    locale = COUNTRY_LOCALE.get(country, "en_US")
    vin = car.get("id", "").split("-", 1)[-1]  # usuń prefix kraju
    return f"https://www.tesla.com/{locale}/m3/order/{vin}?titleStatus=used&redirect=no"

def make_car_id(country, url, title, year):
    """Stabilne ID — nie zmienia się gdy Tesla rotuje parametry URL."""
    slug = url.rstrip("/").split("/")[-1]
    # slug z ev-inventory wygląda jak "TESLA-MODEL3-RWD-ABC123" — stabilny
    if slug and not slug.isdigit() and len(slug) > 4:
        return f"{country}-{slug}"
    # fallback: kraj + znormalizowany tytuł + rok
    safe = re.sub(r"[^a-z0-9]", "-", title.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")[:50]
    return f"{country}-{safe}-{year}"


def parse_cars_from_html(html, country, label="CPO"):
    cars = {}
    car_blocks = re.findall(
        r"<div\s+class\s*=\s*['\"]car['\"].*?(?=<div\s+class\s*=\s*['\"]car['\"]|$)",
        html, re.DOTALL
    )
    for block in car_blocks:
        try:
            url_match = re.search(r"href='(https://ev-inventory\.com/car/[^']+)'", block)
            if not url_match:
                url_match = re.search(r'href="(https://ev-inventory\.com/car/[^"]+)"', block)
            if not url_match:
                continue
            url = url_match.group(1)

            title_match = re.search(r"<h2[^>]*>.*?<a[^>]*>(.*?)</a>", block, re.DOTALL)
            title = re.sub(r"<[^>]+>", " ", title_match.group(1)).strip() if title_match else ""
            title = re.sub(r"\s+", " ", title).strip()

            year_match = re.search(r"<small>\s*(\d{4})\s*</small>", block)
            year = int(year_match.group(1)) if year_match else 0

            price = 0
            price_match = re.search(r"([\d\s,.']+)\s*(?:€|kr|DKK|SEK|EUR)", block)
            if not price_match:
                price_match = re.search(r"(?:€|kr|DKK|SEK|EUR)\s*([\d\s,.']+)", block)
            if price_match:
                price_str = re.sub(r"[^\d]", "", price_match.group(1))
                price = int(price_str) if price_str else 0

            mileage = 0
            mileage_str = ""
            mileage_match = re.search(r"([\d\s,.']+)\s*km", block, re.IGNORECASE)
            if mileage_match:
                mileage_str = mileage_match.group(0).strip()
                mileage_clean = re.sub(r"[^\d]", "", mileage_match.group(1))
                mileage = int(mileage_clean) if mileage_clean else 0

            if mileage and mileage > MAX_KM:
                continue

            img_match = re.search(r"<img\s+src=['\"]([^'\"]+)['\"]", block)
            image_url = img_match.group(1) if img_match else ""
            if image_url and not image_url.startswith("http"):
                image_url = "https://ev-inventory.com" + image_url

            car_id = make_car_id(country, url, title, year)

            cars[car_id] = {
                "id": car_id,
                "url": url,
                "title": title,
                "year": year,
                "price": price,
                "mileage": mileage,
                "mileage_str": mileage_str,
                "country": country,
                "listing_type": label,
                "image_url": image_url,
            }
        except Exception as e:
            print(f"  Błąd parsowania: {e}")
    return cars


def fetch_country(session, country_cfg, rates):
    country = country_cfg["name"]
    currency = country_cfg["currency"]
    max_local = get_max_local(currency, rates)
    print(f"\n  [{country}] max={max_local} {currency}, max_km={MAX_KM}")

    min_year = MIN_YEAR_CPO if country_cfg.get("label") == "CPO" else MIN_YEAR_USED
    form_data = {
        "country": country, "state": "", "sortsale": "256",
        "token": country_cfg["token"], "spec": "0", "advanced": "0",
        "miles": "99999", "max": str(max_local),
        "minyear": str(min_year), "maxyear": str(MAX_YEAR),
        "minrange": "0", "offset": "0",
    }

    all_cars = {}
    offset = 0
    while True:
        form_data["offset"] = str(offset)
        resp = session.post(API_URL, data=form_data, headers=HEADERS, timeout=20)
        print(f"  Status: {resp.status_code}, offset={offset}")
        if resp.status_code != 200:
            break
        html = resp.text.strip()
        if not html or html == "0":
            break
        batch = parse_cars_from_html(html, country, country_cfg.get("label", "CPO"))
        print(f"  Sparsowano: {len(batch)} aut")
        if not batch:
            break
        prev_count = len(all_cars)
        all_cars.update(batch)
        offset += len(batch)
        if len(all_cars) == prev_count:
            break
        time.sleep(1)
    return all_cars


def fetch_all_cars(rates):
    all_cars = {}
    session = cf_requests.Session(impersonate="chrome120")
    print("  Pobieram cookies...")
    try:
        session.get("https://ev-inventory.com/for-sale/Netherlands/M3/CPO/",
                    headers={"user-agent": HEADERS["user-agent"]}, timeout=15)
        time.sleep(2)
        print("  Cookies OK")
    except Exception as e:
        print(f"  Cookies error: {e}")

    mode = os.environ.get("MONITOR_MODE", "ALL")
    print(f"  Tryb: {mode}")

    for country_cfg in COUNTRIES:
        for listing in LISTING_TYPES:
            if mode == "CPO" and listing["label"] != "CPO":
                continue
            if mode == "USED" and listing["label"] != "Used":
                continue
            cfg = {**country_cfg, "token": listing["token"], "label": listing["label"]}
            cars = fetch_country(session, cfg, rates)
            all_cars.update(cars)
            time.sleep(2)
    return all_cars


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def update_history(history, car_id, price, currency, rates):
    if car_id not in history:
        history[car_id] = []
    last = history[car_id][-1] if history[car_id] else None
    if not last or last["price"] != price:
        history[car_id].append({
            "price": price,
            "eur": round(to_eur(price, currency, rates)),
            "pln": round(to_pln(price, currency, rates)),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        })
    history[car_id] = history[car_id][-20:]
    return history


def format_price_history(history_entries):
    if len(history_entries) < 2:
        return None
    lines = []
    prev = None
    for entry in history_entries[-5:]:
        if prev is None:
            trend = ""
        elif entry["eur"] < prev:
            trend = " 📉"
        elif entry["eur"] > prev:
            trend = " 📈"
        else:
            trend = ""
        lines.append(f"{entry['date']}: €{entry['eur']:,}{trend}".replace(",", " "))
        prev = entry["eur"]
    return "\n".join(lines)


def send_discord(embeds):
    payload = {"embeds": embeds}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    print(f"  Discord: {resp.status_code}")
    resp.raise_for_status()


def build_new_car_embed(car_id, car, price, rates):
    country = car.get("country", "")
    currency = get_currency_for_country(country)
    flag = COUNTRY_FLAGS.get(country, "🇪🇺")
    price_eur = int(to_eur(price, currency, rates)) if price else 0
    price_pln = int(to_pln(price, currency, rates)) if price else 0
    mileage = car.get("mileage_str", "—") or "—"
    year = car.get("year", "—")
    url = tesla_url(car)

    lines = [
        f"{flag} **{car.get('title', 'Tesla Model 3')}**",
        f"💰 €{price_eur:,} (~{price_pln:,} zł)".replace(",", " "),
        f"📅 {year}  |  🛣️ {mileage}",
        f"🔗 [Zobacz na Tesla.com]({url})",
    ]

    return {
        "title": f"🚗 Nowe Tesla w ofercie! {flag}",
        "description": "\n".join(lines),
        "color": 0x1DB954,
        "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_price_drop_embed(car_id, car, old_price, new_price, rates, history):
    country = car.get("country", "")
    currency = get_currency_for_country(country)
    flag = COUNTRY_FLAGS.get(country, "🇪🇺")

    old_eur = int(to_eur(old_price, currency, rates))
    new_eur = int(to_eur(new_price, currency, rates))
    old_pln = int(to_pln(old_price, currency, rates))
    new_pln = int(to_pln(new_price, currency, rates))
    diff_eur = old_eur - new_eur
    diff_pln = old_pln - new_pln
    pct = round((old_price - new_price) / old_price * 100, 1)
    mileage = car.get("mileage_str", "—") or "—"
    year = car.get("year", "—")
    url = tesla_url(car)

    lines = [
        f"{flag} **{car.get('title', 'Tesla Model 3')}**",
        f"💰 €{old_eur:,} → €{new_eur:,} (-€{diff_eur:,}, -{pct}%)".replace(",", " "),
        f"🇵🇱 {old_pln:,} zł → {new_pln:,} zł (-{diff_pln:,} zł)".replace(",", " "),
        f"📅 {year}  |  🛣️ {mileage}",
        f"🔗 [Zobacz na Tesla.com]({url})",
    ]

    history_entries = history.get(car_id, [])
    history_str = format_price_history(history_entries)
    if history_str:
        lines.append(f"\n📊 Historia:\n{history_str}")

    return {
        "title": f"📉 Spadek ceny! {flag}",
        "description": "\n".join(lines),
        "color": 0xF0A500,
        "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_daily_summary_embed(current_cars, rates):
    if not current_cars:
        return {
            "title": "📊 Dzienne podsumowanie",
            "description": "Brak aut spełniających kryteria.",
            "color": 0x3498db,
            "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
        }
    by_country = {}
    for car_id, car in current_cars.items():
        c = car.get("country", "?")
        by_country.setdefault(c, []).append(car)
    fields = []
    for country, cars in sorted(by_country.items()):
        flag = COUNTRY_FLAGS.get(country, "🇪🇺")
        currency = get_currency_for_country(country)
        lines = []
        for car in sorted(cars, key=lambda x: x.get("price", 0)):
            price = car.get("price", 0)
            price_eur = int(to_eur(price, currency, rates)) if price else 0
            price_pln = int(to_pln(price, currency, rates)) if price else 0
            title = car.get("title", "?")[:40]
            mileage = car.get("mileage_str", "") or ""
            lines.append(f"[{title}]({car.get('url', '')}) — €{price_eur:,} / {price_pln:,} zł {mileage}".replace(",", " "))
        fields.append({
            "name": f"{flag} {country} ({len(cars)} aut)",
            "value": "\n".join(lines[:10]) or "brak",
            "inline": False,
        })
    return {
        "title": f"📊 Dzienne podsumowanie — {len(current_cars)} aut",
        "description": f"Filtr: CPO {MIN_YEAR_CPO}–{MAX_YEAR}, max €{MAX_EUR:,}, max {MAX_KM:,} km".replace(",", " "),
        "color": 0x3498db,
        "fields": fields[:25],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def should_send_daily_summary():
    now = datetime.now(timezone.utc)
    return now.hour == 8 and now.minute < 15


def main():
    global STATE_FILE, HISTORY_FILE
    mode = os.environ.get("MONITOR_MODE", "ALL")
    STATE_FILE = f"cars_state_{mode.lower()}.json"
    HISTORY_FILE = f"price_history_{mode.lower()}.json"

    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Start monitorowania...")
    print(f"  Pliki stanu: {STATE_FILE}, {HISTORY_FILE}")

    # ── KLUCZOWY FIX: pierwsze uruchomienie = brak pliku stanu ──
    is_first_run = not os.path.exists(STATE_FILE)
    if is_first_run:
        print("  ⚠️  Pierwsze uruchomienie — zapisuję stan BEZ wysyłania powiadomień.")

    print("\nPobieram kursy walut...")
    rates = get_exchange_rates()

    print("\nPobieram auta...")
    current_cars = fetch_all_cars(rates)
    print(f"\nAut łącznie: {len(current_cars)}")

    previous_state = load_state()
    history = load_history()
    print(f"Poprzedni stan: {len(previous_state)} aut")

    for car_id, car in current_cars.items():
        price = car.get("price")
        if price:
            currency = get_currency_for_country(car.get("country", ""))
            history = update_history(history, car_id, price, currency, rates)

    embeds_new   = []
    embeds_drops = []

    if not is_first_run:
        # nowe auta
        for car_id, car in current_cars.items():
            price = car.get("price")
            if car_id not in previous_state:
                print(f"  NOWE: {car_id} {price}")
                embeds_new.append(build_new_car_embed(car_id, car, price, rates))

        # tylko spadki cen (wzrosty pomijamy)
        for car_id, car in current_cars.items():
            price     = car.get("price")
            old_price = previous_state.get(car_id, {}).get("price")
            if price and old_price and price < old_price:
                print(f"  SPADEK: {car_id} {old_price} -> {price}")
                embeds_drops.append(build_price_drop_embed(car_id, car, old_price, price, rates, history))
            elif price and old_price and price > old_price:
                print(f"  WZROST (pominięty): {car_id} {old_price} -> {price}")
    else:
        print(f"  Pierwsze uruchomienie — pominięto {len(current_cars)} aut.")

    save_state({
        car_id: {
            "price": car.get("price"),
            "title": car.get("title", ""),
            "country": car.get("country", ""),
            "url": car.get("url", ""),
            "seen_at": now.strftime("%Y-%m-%d %H:%M"),
        }
        for car_id, car in current_cars.items()
    })
    save_history(history)

    # wysyłaj osobno: najpierw nowe, potem spadki
    if embeds_new:
        for i in range(0, len(embeds_new), 10):
            send_discord(embeds_new[i:i+10])
        print(f"  Wysłano {len(embeds_new)} powiadomień o nowych autach.")

    if embeds_drops:
        for i in range(0, len(embeds_drops), 10):
            send_discord(embeds_drops[i:i+10])
        print(f"  Wysłano {len(embeds_drops)} powiadomień o spadkach cen.")

    if should_send_daily_summary() and not is_first_run:
        send_discord([build_daily_summary_embed(current_cars, rates)])
        print("  Wysłano dzienne podsumowanie.")

    # powiadomienie testowe — tylko przy ręcznym uruchomieniu
    is_manual = os.environ.get("MANUAL_RUN", "false").lower() == "true"
    if is_manual:
        lines = []
        country_set = sorted(set(car.get("country", "?") for car in current_cars.values()))
        for country in country_set:
            flag = COUNTRY_FLAGS.get(country, "🇪🇺")
            currency = get_currency_for_country(country)
            country_cars = [c for c in current_cars.values() if c.get("country") == country]
            for car in sorted(country_cars, key=lambda x: x.get("price", 0)):
                price = car.get("price", 0)
                price_eur = int(to_eur(price, currency, rates)) if price else 0
                lines.append(f"{flag} [{car.get('title','?')}]({car.get('url','')}) — \u20ac{price_eur:,}".replace(",", " "))

        send_discord([{
            "title": "\U0001f527 Test — bot dziala!",
            "description": "\n".join(lines) if lines else "Brak aut spelniajacych kryteria.",
            "color": 0x3498db,
            "fields": [
                {"name": "Aut w ofercie", "value": str(len(current_cars)), "inline": True},
                {"name": "Filtr ceny",    "value": f"max \u20ac{MAX_EUR:,}".replace(",", " "), "inline": True},
                {"name": "Filtr km",      "value": f"max {MAX_KM:,} km".replace(",", " "), "inline": True},
                {"name": "Roczniki",      "value": f"{MIN_YEAR_CPO}\u2013{MAX_YEAR}", "inline": True},
            ],
            "footer": {"text": f"Tesla CPO Monitor \u00b7 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
        }])
        print("  Wyslano powiadomienie testowe.")
    elif not embeds_new and not embeds_drops:
        print("Brak zmian.")


if __name__ == "__main__":
    main()
