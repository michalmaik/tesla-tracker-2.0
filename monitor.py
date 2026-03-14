import json
import time
from datetime import datetime
from curl_cffi import requests as cf_requests
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"

API_URL = "https://ev-inventory.com/lib/get_stock_23.php"

FORM_DATA = {
    "country": "Netherlands",
    "state": "",
    "sortsale": "256",
    "token": "131076",
    "spec": "0",
    "advanced": "0",
    "miles": "99999",
    "max": "20000",
    "minyear": "2020",
    "maxyear": "2021",
    "minrange": "0",
    "offset": "0",
}

HEADERS = {
    "authority": "ev-inventory.com",
    "accept": "*/*",
    "accept-language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://ev-inventory.com",
    "referer": "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/?state=&miles=99999&max=99999999&year=20192026&sortsale=256&token=131076&spec=0&adv=0&minrange=0",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}


def fetch_cars():
    all_cars = {}
    offset = 0
    session = cf_requests.Session(impersonate="chrome120")

    # najpierw odwiedz strone glowna zeby dostac cookies
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
        print(f"  Cookies error (ignoruję): {e}")

    while True:
        data = dict(FORM_DATA)
        data["offset"] = str(offset)

        resp = session.post(API_URL, data=data, headers=HEADERS, timeout=20)
        print(f"  Status: {resp.status_code}, offset={offset}")

        if resp.status_code != 200:
            print(f"  Body: {resp.text[:300]}")
            resp.raise_for_status()

        try:
            result = resp.json()
        except Exception:
            print(f"  Nie JSON: {resp.text[:300]}")
            raise

        cars = result.get("results", [])
        total = int(result.get("total", 0))
        print(f"  Wyników: {len(cars)}, total: {total}")

        if not cars:
            break

        for car in cars:
            car_id = str(car.get("id") or car.get("vin") or car.get("stock_no", ""))
            if car_id:
                all_cars[car_id] = car

        offset += len(cars)
        if offset >= total:
            break

    return all_cars


def get_price(car):
    for field in ["price", "sale_price", "asking_price", "list_price"]:
        val = car.get(field)
        if val:
            try:
                clean = str(val).replace(",", "").replace(".", "").replace(" ", "").replace("€", "")
                return int(clean)
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
    variant = car.get("trim") or car.get("variant") or car.get("spec_name") or ""
    color = car.get("color") or car.get("colour") or ""
    mileage = car.get("miles") or car.get("odometer") or car.get("mileage") or ""
    parts = [x for x in [str(year), "Model 3", variant, color] if x]
    info = " · ".join(parts)
    if mileage:
        info += f" · {mileage} km"
    return info or "Tesla Model 3"


def send_discord(embeds):
    payload = {"embeds": embeds}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    print(f"  Discord: {resp.status_code}")
    resp.raise_for_status()


def build_new_car_embed(car_id, car, price):
    price_str = f"€{price:,}".replace(",", " ") if price else "brak ceny"
    return {
        "title": "🚗 Nowe Tesla w ofercie!",
        "description": format_car_info(car),
        "url": get_car_url(car),
        "color": 0x1DB954,
        "fields": [
            {"name": "Cena", "value": price_str, "inline": True},
            {"name": "Kraj", "value": "Holandia 🇳🇱", "inline": True},
        ],
        "footer": {"text": f"Tesla CPO Monitor · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_price_drop_embed(car_id, car, old_price, new_price):
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
    print(f"  Filtr: 2020-2021, max €20000, Holandia")

    current_cars = fetch_cars()
    print(f"Aut po filtrach: {len(current_cars)}")

    previous_state = load_state()
    print(f"Poprzedni stan: {len(previous_state)} aut")

    embeds = []
    for car_id, car in current_cars.items():
        price = get_price(car)
        if car_id not in previous_state:
            print(f"  NOWE: {car_id} €{price}")
            embeds.append(build_new_car_embed(car_id, car, price))
        else:
            old_price = previous_state[car_id].get("price")
            if price and old_price and price < old_price:
                print(f"  SPADEK: {car_id} €{old_price} -> €{price}")
                embeds.append(build_price_drop_embed(car_id, car, old_price, price))

    save_state({
        car_id: {"price": get_price(car), "seen_at": datetime.utcnow().isoformat()}
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
