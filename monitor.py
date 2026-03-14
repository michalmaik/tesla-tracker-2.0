import requests
import json
from datetime import datetime
import time

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"

API_URL = "https://ev-inventory.com/wp-content/themes/evtheme/get_stock_23.php"
PARAMS = {
    "country": "Netherlands",
    "state": "",
    "sortsale": "256",
    "token": "131076",
    "spec": "0",
    "advanced": "4",
    "miles": "99999",
    "max": "20000",
    "minyear": "2020",
    "maxyear": "2021",
    "minrange": "0",
    "offset": "0",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}


def fetch_cars():
    all_cars = {}
    offset = 0
    session = requests.Session()

    print("  Pobieram cookies z głównej strony...")
    try:
        r = session.get(
            "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/",
            headers={"User-Agent": HEADERS["User-Agent"], "Accept": "text/html,*/*"},
            timeout=15,
        )
        print(f"  Strona główna status: {r.status_code}, cookies: {dict(session.cookies)}")
        time.sleep(2)
    except Exception as e:
        print(f"  Uwaga cookies: {e}")

    while True:
        params = dict(PARAMS)
        params["offset"] = offset
        resp = session.get(API_URL, params=params, headers=HEADERS, timeout=15)
        print(f"  API status: {resp.status_code}")
        print(f"  API response (pierwsze 500 znaków): {resp.text[:500]}")

        if resp.status_code == 404:
            print("  BLOKADA 404 - strona blokuje GitHub Actions IP")
            print("  Próbuję bez session...")
            resp2 = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
            print(f"  Bez session status: {resp2.status_code}, body: {resp2.text[:300]}")
            resp.raise_for_status()

        resp.raise_for_status()

        try:
            data = resp.json()
        except Exception:
            print(f"  Nie jest JSON: {resp.text[:500]}")
            raise

        cars = data.get("results", [])
        print(f"  offset={offset}, wyniki={len(cars)}, total={data.get('total')}")
        if not cars:
            break

        for car in cars:
            car_id = str(car.get("id") or car.get("vin") or car.get("stock_no", ""))
            if car_id:
                all_cars[car_id] = car

        total = int(data.get("total", 0))
        offset += len(cars)
        if offset >= total:
            break

    return all_cars


def get_price(car):
    for field in ["price", "sale_price", "asking_price", "list_price"]:
        val = car.get(field)
        if val:
            try:
                return int(str(val).replace(",", "").replace(".", "").replace(" ", "").replace("€", ""))
            except Exception:
                pass
    return None


def get_car_url(car):
    slug = car.get("slug") or car.get("url") or ""
    if slug and not slug.startswith("http"):
        return f"https://ev-inventory.com/listing/{slug}"
    return slug or "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/"


def format_car_info(car):
    year = car.get("year", "")
    model = car.get("model", "Model 3")
    variant = car.get("trim") or car.get("variant") or car.get("spec_name") or ""
    color = car.get("color") or car.get("colour") or ""
    mileage = car.get("miles") or car.get("odometer") or car.get("mileage") or ""
    parts = [x for x in [str(year), model, variant, color] if x]
    info = " · ".join(parts)
    if mileage:
        info += f" · {mileage} km"
    return info


def send_discord(embeds):
    payload = {"embeds": embeds}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    print(f"  Discord status: {resp.status_code}")
    resp.raise_for_status()


def build_new_car_embed(car, price):
    url = get_car_url(car)
    price_str = f"€{price:,}".replace(",", " ") if price else "brak ceny"
    return {
        "title": "🚗 Nowe auto w ofercie!",
        "description": format_car_info(car),
        "url": url,
        "color": 0x1DB954,
        "fields": [
            {"name": "Cena", "value": price_str, "inline": True},
            {"name": "Kraj", "value": "Holandia 🇳🇱", "inline": True},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_price_drop_embed(car, old_price, new_price):
    url = get_car_url(car)
    diff = old_price - new_price
    pct = round(diff / old_price * 100, 1)
    return {
        "title": "📉 Spadek ceny!",
        "description": format_car_info(car),
        "url": url,
        "color": 0xF0A500,
        "fields": [
            {"name": "Stara cena", "value": f"€{old_price:,}".replace(",", " "), "inline": True},
            {"name": "Nowa cena", "value": f"€{new_price:,}".replace(",", " "), "inline": True},
            {"name": "Obniżka", "value": f"-€{diff:,} (-{pct}%)".replace(",", " "), "inline": False},
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
    print(f"[{datetime.utcnow().isoformat()}] Pobieranie aut...")
    current_cars = fetch_cars()
    print(f"Znaleziono {len(current_cars)} aut.")

    previous_state = load_state()
    print(f"Poprzedni stan: {len(previous_state)} aut.")

    embeds = []
    for car_id, car in current_cars.items():
        price = get_price(car)
        if car_id not in previous_state:
            print(f"  NOWE: {car_id}")
            embeds.append(build_new_car_embed(car, price))
        else:
            old_price = previous_state[car_id].get("price")
            if price and old_price and price < old_price:
                print(f"  SPADEK: {car_id} {old_price} -> {price}")
                embeds.append(build_price_drop_embed(car, old_price, price))

    save_state({
        car_id: {"price": get_price(car), "seen_at": datetime.utcnow().isoformat()}
        for car_id, car in current_cars.items()
    })

    if embeds:
        for i in range(0, len(embeds), 10):
            send_discord(embeds[i:i+10])
        print(f"Wysłano {len(embeds)} powiadomień.")
    else:
        print("Brak zmian.")


if __name__ == "__main__":
    main()
