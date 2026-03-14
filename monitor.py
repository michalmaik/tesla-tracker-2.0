import json
import time
import re
from datetime import datetime
from curl_cffi import requests as cf_requests
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"

API_URL = "https://ev-inventory.com/lib/get_stock_23.php"

# kraje z ich walutami i tokenami
COUNTRIES = [
    {"name": "Netherlands", "currency": "EUR", "token": "131076"},
    {"name": "Germany",     "currency": "EUR", "token": "131076"},
    {"name": "France",      "currency": "EUR", "token": "131076"},
    {"name": "Belgium",     "currency": "EUR", "token": "131076"},
    {"name": "Luxembourg",  "currency": "EUR", "token": "131076"},
    {"name": "Sweden",      "currency": "SEK", "token": "131076"},
    {"name": "Denmark",     "currency": "DKK", "token": "131076"},
]

COUNTRY_FLAGS = {
    "Netherlands": "🇳🇱",
    "Germany":     "🇩🇪",
    "France":      "🇫🇷",
    "Belgium":     "🇧🇪",
    "Luxembourg":  "🇱🇺",
    "Sweden":      "🇸🇪",
    "Denmark":     "🇩🇰",
}

MAX_EUR = 20000
MIN_YEAR = 2018
MAX_YEAR = 2021

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
    """Pobierz aktualne kursy walut względem PLN"""
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest?from=PLN&to=EUR,SEK,DKK",
            timeout=10
        )
        data = resp.json()
        rates = data.get("rates", {})
        # frankfurter zwraca ile PLN = 1 waluta, wiec odwracamy
        result = {}
        for currency, rate in rates.items():
            result[currency] = 1.0 / rate  # ile PLN za 1 jednostke waluty
        result["PLN"] = 1.0
        print(f"  Kursy: EUR={result.get('EUR', 0):.2f} PLN, SEK={result.get('SEK', 0):.4f} PLN, DKK={result.get('DKK', 0):.4f} PLN")
        return result
    except Exception as e:
        print(f"  Błąd pobierania kursów: {e}, używam przybliżonych")
        return {"EUR": 4.25, "SEK": 0.40, "DKK": 0.57, "PLN": 1.0}


def to_eur(price, currency, rates):
    """Przelicz cenę na EUR"""
    if currency == "EUR":
        return price
    pln = price * rates.get(currency, 1.0)
    eur_rate = rates.get("EUR", 4.25)
    return pln / eur_rate


def to_pln(price, currency, rates):
    """Przelicz cenę na PLN"""
    return price * rates.get(currency, 1.0)


def get_currency_max(currency, rates):
    """Ile max w danej walucie odpowiada MAX_EUR"""
    if currency == "EUR":
        return MAX_EUR
    eur_rate = rates.get("EUR", 4.25)
    currency_rate = rates.get(currency, 1.0)
    # MAX_EUR EUR * eur_rate PLN/EUR / currency_rate PLN/currency
    return int(MAX_EUR * eur_rate / currency_rate)


def parse_cars_from_html(html, country):
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

            mileage_match = re.search(r"([\d\s,.']+)\s*km", block, re.IGNORECASE)
            mileage = mileage_match.group(0).strip() if mileage_match else ""

            cars[car_id] = {
                "id": car_id,
                "url": url,
                "title": title,
                "year": year,
                "price": price,
                "mileage": mileage,
                "country": country,
            }
        except Exception as e:
            print(f"  Błąd parsowania: {e}")

    return cars


def fetch_country(session, country_cfg, rates):
    country = country_cfg["name"]
    currency = country_cfg["currency"]
    max_local = get_currency_max(currency, rates)

    print(f"\n  [{country}] max={max_local} {currency}")

    form_data = {
        "country": country,
        "state": "",
        "sortsale": "256",
        "token": country_cfg["token"],
        "spec": "0",
        "advanced": "0",
        "miles": "99999",
        "max": str(max_local),
        "minyear": str(MIN_YEAR),
        "maxyear": str(MAX_YEAR),
        "minrange": "0",
        "offset": "0",
    }

    all_cars = {}
    offset = 0

    while True:
        form_data["offset"] = str(offset)
        resp = session.post(API_URL, data=form_data, headers=HEADERS, timeout=20)
        print(f"  Status: {resp.status_code}, offset={offset}")

        if resp.status_code != 200:
            print(f"  Error: {resp.text[:200]}")
            break

        html = resp.text.strip()
        if not html or html == "0":
            break

        batch = parse_cars_from_html(html, country)
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
        session.get(
            "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/",
            headers={"user-agent": HEADERS["user-agent"]},
            timeout=15,
        )
        time.sleep(2)
        print("  Cookies OK")
    except Exception as e:
        print(f"  Cookies error: {e}")

    for country_cfg in COUNTRIES:
        cars = fetch_country(session, country_cfg, rates)
        all_cars.update(cars)
        time.sleep(2)

    return all_cars


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

    price_eur = to_eur(price, currency, rates) if price else 0
    price_pln = to_pln(price, currency, rates) if price else 0

    if currency == "EUR":
        price_local_str = f"€{price:,}".replace(",", " ")
    elif currency == "SEK":
        price_local_str = f"{price:,} kr".replace(",", " ")
    elif currency == "DKK":
        price_local_str = f"{price:,} DKK".replace(",", " ")
    else:
        price_local_str = f"{price:,} {currency}".replace(",", " ")

    return {
        "title": f"🚗 Nowe Tesla w ofercie! {flag}",
        "description": car.get("title", "Tesla Model 3"),
        "url": car.get("url", ""),
        "color": 0x1DB954,
        "fields": [
            {"name": "Cena lokalna", "value": price_local_str if price else "brak", "inline": True},
            {"name": "≈ EUR", "value": f"€{int(price_eur):,}".replace(",", " ") if price_eur else "—", "inline": True},
            {"name": "≈ PLN", "value": f"{int(price_pln):,} zł".replace(",", " ") if price_pln else "—", "inline": True},
            {"name": "Kraj", "value": f"{flag} {country}", "inline": True},
            {"name": "Przebieg", "value": car.get("mileage", "—") or "—", "inline": True},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_price_drop_embed(car_id, car, old_price, new_price, rates):
    country = car.get("country", "")
    currency = get_currency_for_country(country)
    flag = COUNTRY_FLAGS.get(country, "🇪🇺")

    old_pln = to_pln(old_price, currency, rates)
    new_pln = to_pln(new_price, currency, rates)
    old_eur = to_eur(old_price, currency, rates)
    new_eur = to_eur(new_price, currency, rates)
    diff_pln = old_pln - new_pln
    pct = round(diff_pln / old_pln * 100, 1)

    return {
        "title": f"📉 Spadek ceny! {flag}",
        "description": car.get("title", "Tesla Model 3"),
        "url": car.get("url", ""),
        "color": 0xF0A500,
        "fields": [
            {"name": "Stara cena (EUR)", "value": f"€{int(old_eur):,}".replace(",", " "), "inline": True},
            {"name": "Nowa cena (EUR)", "value": f"€{int(new_eur):,}".replace(",", " "), "inline": True},
            {"name": "Stara cena (PLN)", "value": f"{int(old_pln):,} zł".replace(",", " "), "inline": True},
            {"name": "Nowa cena (PLN)", "value": f"{int(new_pln):,} zł".replace(",", " "), "inline": True},
            {"name": "Obniżka", "value": f"-{int(diff_pln):,} zł (-{pct}%)".replace(",", " "), "inline": False},
            {"name": "Kraj", "value": f"{flag} {country}", "inline": True},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    print(f"[{datetime.utcnow().isoformat()}] Start monitorowania...")
    print(f"  Filtr: {MIN_YEAR}-{MAX_YEAR}, max €{MAX_EUR}, kraje: {[c['name'] for c in COUNTRIES]}")

    print("\nPobieram kursy walut...")
    rates = get_exchange_rates()

    print("\nPobieram auta...")
    current_cars = fetch_all_cars(rates)
    print(f"\nAut łącznie: {len(current_cars)}")

    previous_state = load_state()
    print(f"Poprzedni stan: {len(previous_state)} aut")

    embeds = []
    for car_id, car in current_cars.items():
        price = car.get("price")
        if car_id not in previous_state:
            print(f"  NOWE: {car_id} {price}")
            embeds.append(build_new_car_embed(car_id, car, price, rates))
        else:
            old_price = previous_state[car_id].get("price")
            if price and old_price and price < old_price:
                print(f"  SPADEK: {car_id} {old_price} -> {price}")
                embeds.append(build_price_drop_embed(car_id, car, old_price, price, rates))

    save_state({
        car_id: {"price": car.get("price"), "seen_at": datetime.utcnow().isoformat()}
        for car_id, car in current_cars.items()
    })

    if embeds:
        for i in range(0, len(embeds), 10):
            send_discord(embeds[i:i+10])
        print(f"Wysłano {len(embeds)} powiadomień.")
    else:
        print("Brak zmian — nic nie wysłano.")


if __name__ == "__main__":
    main()
