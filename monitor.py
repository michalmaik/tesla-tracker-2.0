import json
import time
import re
from datetime import datetime, timezone
from curl_cffi import requests as cf_requests
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"
HISTORY_FILE = "price_history.json"

API_URL = "https://ev-inventory.com/lib/get_stock_23.php"

# tokeny: 131076 = CPO, 65540 = Used
LISTING_TYPES = [
    {"token": "131076", "label": "CPO"},
    {"token": "65540",  "label": "Used"},
]

COUNTRIES = [
    # EUR
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
    # SEK
    {"name": "Sweden",         "currency": "SEK"},
    # DKK
    {"name": "Denmark",        "currency": "DKK"},
    # PLN
    {"name": "Poland",         "currency": "PLN"},
    # CZK
    {"name": "Czech Republic",  "currency": "CZK"},
    # HUF
    {"name": "Hungary",        "currency": "HUF"},
    # RON
    {"name": "Romania",        "currency": "RON"},
    # BGN
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

MAX_EUR = 20000
MIN_YEAR_CPO = 2019
MIN_YEAR_USED = 2020
MAX_YEAR = 2021
MAX_KM = 150000  # max przebieg w km

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
        # BGN jest peg do EUR: 1 EUR = 1.956 BGN
        if not result.get("BGN") or result["BGN"] == 0:
            result["BGN"] = result.get("EUR", 4.25) / 1.956
        print(f"  Kursy: EUR={result.get('EUR',0):.2f} SEK={result.get('SEK',0):.4f} DKK={result.get('DKK',0):.4f} CZK={result.get('CZK',0):.4f} HUF={result.get('HUF',0):.5f} RON={result.get('RON',0):.4f} BGN={result.get('BGN',0):.4f} PLN")
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
            car_id = f"{country}-{url.split('/')[-1]}"

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

            # filtruj przebieg
            if mileage and mileage > MAX_KM:
                continue

            # wyciagnij zdjecie
            img_match = re.search(r"<img\s+src=['\"]([^'\"]+)['\"]", block)
            image_url = img_match.group(1) if img_match else ""
            if image_url and not image_url.startswith("http"):
                image_url = "https://ev-inventory.com" + image_url

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

        all_cars.update(batch)
        offset += len(batch)
        if len(batch) < 10:
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

    for country_cfg in COUNTRIES:
        for listing in LISTING_TYPES:
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
    # zachowaj max 20 wpisow
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


def build_price_rise_embed(car_id, car, old_price, new_price, rates):
    country = car.get("country", "")
    currency = get_currency_for_country(country)
    flag = COUNTRY_FLAGS.get(country, "🇪🇺")
    old_eur = int(to_eur(old_price, currency, rates))
    new_eur = int(to_eur(new_price, currency, rates))
    old_pln = int(to_pln(old_price, currency, rates))
    new_pln = int(to_pln(new_price, currency, rates))
    diff_eur = new_eur - old_eur
    diff_pln = new_pln - old_pln
    pct = round((new_price - old_price) / old_price * 100, 1)
    embed = {
        "title": f"📈 Wzrost ceny! {flag}",
        "description": car.get("title", "Tesla Model 3"),
        "url": car.get("url", ""),
        "color": 0xe74c3c,
        "fields": [
            {"name": "Stara cena (EUR)", "value": f"€{old_eur:,}".replace(",", " "), "inline": True},
            {"name": "Nowa cena (EUR)", "value": f"€{new_eur:,}".replace(",", " "), "inline": True},
            {"name": "Wzrost (EUR)", "value": f"+€{diff_eur:,} (+{pct}%)".replace(",", " "), "inline": True},
            {"name": "Stara cena (PLN)", "value": f"{old_pln:,} zł".replace(",", " "), "inline": True},
            {"name": "Nowa cena (PLN)", "value": f"{new_pln:,} zł".replace(",", " "), "inline": True},
            {"name": "Wzrost (PLN)", "value": f"+{diff_pln:,} zł (+{pct}%)".replace(",", " "), "inline": True},
            {"name": "Kraj", "value": f"{flag} {country}", "inline": True},
            {"name": "Typ", "value": car.get("listing_type", "CPO"), "inline": True},
        ],
        "footer": {"text": f"Tesla Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }
    if car.get("image_url"):
        embed["image"] = {"url": car["image_url"]}
    return embed


def send_discord(embeds):
    payload = {"embeds": embeds}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    print(f"  Discord: {resp.status_code}")
    resp.raise_for_status()


def get_currency_for_country(country):
    for c in COUNTRIES:
        if c["name"] == country:
            return c["currency"]
    return "EUR"


def build_new_car_embed(car_id, car, price, rates):
    country = car.get("country", "")
    currency = get_currency_for_country(country)
    flag = COUNTRY_FLAGS.get(country, "🇪🇺")
    price_eur = int(to_eur(price, currency, rates)) if price else 0
    price_pln = int(to_pln(price, currency, rates)) if price else 0

    if currency == "EUR":
        price_local_str = f"€{price:,}".replace(",", " ")
    elif currency == "SEK":
        price_local_str = f"{price:,} kr".replace(",", " ")
    else:
        price_local_str = f"{price:,} {currency}".replace(",", " ")

    embed = {
        "title": f"🚗 Nowe Tesla w ofercie! {flag}",
        "description": car.get("title", "Tesla Model 3"),
        "url": car.get("url", ""),
        "color": 0x1DB954,
        "fields": [
            {"name": "Cena lokalna", "value": price_local_str if price else "brak", "inline": True},
            {"name": "≈ EUR", "value": f"€{price_eur:,}".replace(",", " "), "inline": True},
            {"name": "≈ PLN", "value": f"{price_pln:,} zł".replace(",", " "), "inline": True},
            {"name": "Kraj", "value": f"{flag} {country}", "inline": True},
            {"name": "Rok", "value": str(car.get("year", "—")), "inline": True},
            {"name": "Przebieg", "value": car.get("mileage_str", "—") or "—", "inline": True},
            {"name": "Typ", "value": car.get("listing_type", "CPO"), "inline": True},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }
    if car.get("image_url"):
        embed["image"] = {"url": car["image_url"]}
    return embed


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

    embed = {
        "title": f"📉 Spadek ceny! {flag}",
        "description": car.get("title", "Tesla Model 3"),
        "url": car.get("url", ""),
        "color": 0xF0A500,
        "fields": [
            {"name": "Stara cena (EUR)", "value": f"€{old_eur:,}".replace(",", " "), "inline": True},
            {"name": "Nowa cena (EUR)", "value": f"€{new_eur:,}".replace(",", " "), "inline": True},
            {"name": "Obniżka (EUR)", "value": f"-€{diff_eur:,} (-{pct}%)".replace(",", " "), "inline": True},
            {"name": "Stara cena (PLN)", "value": f"{old_pln:,} zł".replace(",", " "), "inline": True},
            {"name": "Nowa cena (PLN)", "value": f"{new_pln:,} zł".replace(",", " "), "inline": True},
            {"name": "Obniżka (PLN)", "value": f"-{diff_pln:,} zł".replace(",", " "), "inline": True},
            {"name": "Kraj", "value": f"{flag} {country}", "inline": True},
            {"name": "Rok", "value": str(car.get("year", "—")), "inline": True},
            {"name": "Przebieg", "value": car.get("mileage_str", "—") or "—", "inline": True},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }

    history_entries = history.get(car_id, [])
    history_str = format_price_history(history_entries)
    if history_str:
        embed["fields"].append({"name": "Historia cen (EUR)", "value": history_str, "inline": False})

    if car.get("image_url"):
        embed["image"] = {"url": car["image_url"]}
    return embed


def build_removed_car_embed(car_id, car, price, rates):
    country = car.get("country", "")
    currency = get_currency_for_country(country)
    flag = COUNTRY_FLAGS.get(country, "🇪🇺")
    price_eur = int(to_eur(price, currency, rates)) if price else 0
    price_pln = int(to_pln(price, currency, rates)) if price else 0

    return {
        "title": f"✅ Auto sprzedane / zdjęte z oferty {flag}",
        "description": car.get("title", car_id),
        "color": 0x95a5a6,
        "fields": [
            {"name": "Ostatnia cena (EUR)", "value": f"€{price_eur:,}".replace(",", " ") if price else "—", "inline": True},
            {"name": "Ostatnia cena (PLN)", "value": f"{price_pln:,} zł".replace(",", " ") if price else "—", "inline": True},
            {"name": "Kraj", "value": f"{flag} {country}", "inline": True},
        ],
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
        "description": f"Filtr: CPO {MIN_YEAR_CPO}–{MAX_YEAR} / Used {MIN_YEAR_USED}–{MAX_YEAR}, max €{MAX_EUR:,}, max {MAX_KM:,} km".replace(",", " "),
        "color": 0x3498db,
        "fields": fields[:25],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def should_send_daily_summary():
    """Wyslij podsumowanie raz dziennie ok 8:00 UTC"""
    now = datetime.now(timezone.utc)
    return now.hour == 8 and now.minute < 15


def main():
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Start monitorowania...")
    print(f"  Filtr: CPO {MIN_YEAR_CPO}-{MAX_YEAR}, Used {MIN_YEAR_USED}-{MAX_YEAR}, max €{MAX_EUR}, max {MAX_KM} km")

    print("\nPobieram kursy walut...")
    rates = get_exchange_rates()

    print("\nPobieram auta...")
    current_cars = fetch_all_cars(rates)
    print(f"\nAut łącznie: {len(current_cars)}")

    previous_state = load_state()
    history = load_history()
    print(f"Poprzedni stan: {len(previous_state)} aut")

    # zaktualizuj historie cen
    for car_id, car in current_cars.items():
        price = car.get("price")
        if price:
            currency = get_currency_for_country(car.get("country", ""))
            history = update_history(history, car_id, price, currency, rates)

    embeds = []

    # nowe auta
    for car_id, car in current_cars.items():
        price = car.get("price")
        if car_id not in previous_state:
            print(f"  NOWE: {car_id} {price}")
            embeds.append(build_new_car_embed(car_id, car, price, rates))

    # zmiany cen
    for car_id, car in current_cars.items():
        price = car.get("price")
        old_price = previous_state.get(car_id, {}).get("price")
        if price and old_price and price < old_price:
            print(f"  SPADEK: {car_id} {old_price} -> {price}")
            embeds.append(build_price_drop_embed(car_id, car, old_price, price, rates, history))
        elif price and old_price and price > old_price:
            print(f"  WZROST: {car_id} {old_price} -> {price}")
            embeds.append(build_price_rise_embed(car_id, car, old_price, price, rates))

    # usuniete auta (tylko jesli poprzedni stan nie byl pusty)
    if previous_state:
        for car_id, prev in previous_state.items():
            if car_id not in current_cars:
                print(f"  USUNIETE: {car_id}")
                country = prev.get("country", "")
                fake_car = {"title": prev.get("title", car_id), "country": country, "url": prev.get("url", "")}
                embeds.append(build_removed_car_embed(car_id, fake_car, prev.get("price"), rates))

    # dzienne podsumowanie
    if should_send_daily_summary():
        print("  Wysyłam dzienne podsumowanie...")
        embeds.insert(0, build_daily_summary_embed(current_cars, rates))

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

    if embeds:
        for i in range(0, len(embeds), 10):
            send_discord(embeds[i:i+10])
        print(f"Wysłano {len(embeds)} powiadomień.")
    else:
        print("Brak zmian.")


if __name__ == "__main__":
    main()
