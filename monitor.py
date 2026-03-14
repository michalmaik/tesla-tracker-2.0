import json
import urllib.parse
import time
import random
from datetime import datetime
from curl_cffi import requests as cf_requests
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"

TESLA_API = "https://www.tesla.com/inventory/api/v4/inventory-results"

QUERY = {
    "query": {
        "model": "m3",
        "condition": "used",
        "options": {},
        "arrangeby": "Price",
        "order": "asc",
        "market": "NL",
        "language": "nl",
        "super_region": "europe",
        "lng": 4.9,
        "lat": 52.3,
        "zip": "1012",
        "range": 0,
        "region": "NL",
    },
    "offset": 0,
    "count": 50,
    "outsideOffset": 0,
    "outsideSearch": False,
    "isFalconDeliverySelectionEnabled": False,
    "version": None,
}

MAX_PRICE = 20000
MIN_YEAR = 2020
MAX_YEAR = 2021

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.tesla.com/nl_NL/inventory/used/m3",
    "Origin": "https://www.tesla.com",
}


def fetch_with_retry(session, url, max_retries=5):
    for attempt in range(max_retries):
        # losowe opoznienie przed kazdym requestem
        wait = random.uniform(3, 8) + attempt * 5
        print(f"  Czekam {wait:.1f}s przed requestem (próba {attempt+1}/{max_retries})...")
        time.sleep(wait)

        resp = session.get(url, headers=HEADERS, timeout=30)
        print(f"  Status: {resp.status_code}")

        if resp.status_code == 200:
            return resp
        elif resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            print(f"  429 - czekam {retry_after}s...")
            time.sleep(retry_after)
        elif resp.status_code in (403, 404):
            print(f"  {resp.status_code} - body: {resp.text[:200]}")
            resp.raise_for_status()
        else:
            print(f"  Nieoczekiwany status {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()

    raise Exception(f"Nie udało się po {max_retries} próbach")


def fetch_cars():
    all_cars = {}
    offset = 0

    session = cf_requests.Session(impersonate="chrome120")

    # warm up - odwiedz kilka stron jak normalny user
    print("  Warm-up: odwiedzam tesla.com...")
    try:
        session.get("https://www.tesla.com/nl_NL/", timeout=15)
        time.sleep(random.uniform(2, 4))
        session.get("https://www.tesla.com/nl_NL/inventory/used/m3", headers={
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9",
        }, timeout=15)
        time.sleep(random.uniform(3, 6))
        print("  Warm-up OK")
    except Exception as e:
        print(f"  Warm-up error (ignoruję): {e}")

    while True:
        q = dict(QUERY)
        q["offset"] = offset
        encoded = urllib.parse.quote(json.dumps(q))
        url = f"{TESLA_API}?query={encoded}"

        resp = fetch_with_retry(session, url)

        try:
            data = resp.json()
        except Exception:
            print(f"  Nie JSON: {resp.text[:300]}")
            raise

        results = data.get("results", [])
        total = data.get("total_matches_found", 0)
        print(f"  Wyników: {len(results)}, total: {total}")

        for car in results:
            vin = car.get("VIN", "")
            if not vin:
                continue
            year = car.get("Year", 0)
            price = car.get("InventoryPrice") or car.get("Price") or 0
            if year and (year < MIN_YEAR or year > MAX_YEAR):
                continue
            if price and price > MAX_PRICE:
                continue
            all_cars[vin] = car

        offset += len(results)
        if offset >= total or not results:
            break

    return all_cars


def get_price(car):
    return car.get("InventoryPrice") or car.get("Price") or None


def get_car_url(car):
    vin = car.get("VIN", "")
    return f"https://www.tesla.com/nl_NL/used/{vin}" if vin else "https://www.tesla.com/nl_NL/inventory/used/m3"


def format_car_info(car):
    year = car.get("Year", "")
    trim = car.get("TrimName", "")
    color_data = [o for o in car.get("OptionCodeData", []) if o.get("Group") == "PAINT"]
    color = color_data[0].get("Name", "") if color_data else ""
    odometer = car.get("Odometer", "")
    odo_unit = car.get("OdometerType", "km")
    parts = [x for x in [str(year), "Model 3", trim, color] if x]
    info = " · ".join(parts)
    if odometer:
        info += f" · {int(odometer):,} {odo_unit}".replace(",", " ")
    return info or "Tesla Model 3"


def send_discord(embeds):
    payload = {"embeds": embeds}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    print(f"  Discord: {resp.status_code}")
    resp.raise_for_status()


def build_new_car_embed(vin, car, price):
    price_str = f"€{price:,}".replace(",", " ") if price else "brak ceny"
    return {
        "title": "🚗 Nowe Tesla w ofercie!",
        "description": format_car_info(car),
        "url": get_car_url(car),
        "color": 0x1DB954,
        "fields": [
            {"name": "Cena", "value": price_str, "inline": True},
            {"name": "Kraj", "value": "Holandia 🇳🇱", "inline": True},
            {"name": "VIN", "value": vin, "inline": False},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_price_drop_embed(vin, car, old_price, new_price):
    diff = old_price - new_price
    pct = round(diff / old_price * 100, 1)
    return {
        "title": "📉 Spadek ceny!",
        "description": format_car_info(car),
        "url": get_car_url(car),
        "color": 0xF0A500,
        "fields": [
            {"name": "Stara cena", "value": f"€{old_price:,}".replace(",", " "), "inline": True},
            {"name": "Nowa cena", "value": f"€{new_price:,}".replace(",", " "), "inline": True},
            {"name": "Obniżka", "value": f"-€{diff:,} (-{pct}%)".replace(",", " "), "inline": False},
            {"name": "VIN", "value": vin, "inline": False},
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
    print(f"  Filtr: {MIN_YEAR}-{MAX_YEAR}, max €{MAX_PRICE}, Holandia")

    current_cars = fetch_cars()
    print(f"Aut po filtrach: {len(current_cars)}")

    previous_state = load_state()
    print(f"Poprzedni stan: {len(previous_state)} aut")

    embeds = []
    for vin, car in current_cars.items():
        price = get_price(car)
        if vin not in previous_state:
            print(f"  NOWE: {vin} €{price}")
            embeds.append(build_new_car_embed(vin, car, price))
        else:
            old_price = previous_state[vin].get("price")
            if price and old_price and price < old_price:
                print(f"  SPADEK: {vin} €{old_price} -> €{price}")
                embeds.append(build_price_drop_embed(vin, car, old_price, price))

    save_state({
        vin: {"price": get_price(car), "seen_at": datetime.utcnow().isoformat()}
        for vin, car in current_cars.items()
    })

    if embeds:
        for i in range(0, len(embeds), 10):
            send_discord(embeds[i:i+10])
        print(f"Wysłano {len(embeds)} powiadomień.")
    else:
        print("Brak zmian — nic nie wysłano.")


if __name__ == "__main__":
    main()
