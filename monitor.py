import json
import time
import re
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
    "minyear": "2018",
    "maxyear": "2021",
    "minrange": "0",
    "offset": "0",
}

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


def parse_cars_from_html(html):
    cars = {}

    # znajdz wszystkie bloki <div class='car'>
    car_blocks = re.findall(r"<div\s+class\s*=\s*['\"]car['\"].*?(?=<div\s+class\s*=\s*['\"]car['\"]|$)", html, re.DOTALL)
    print(f"  Znaleziono bloków aut: {len(car_blocks)}")

    for block in car_blocks:
        try:
            # URL i ID
            url_match = re.search(r"href='(https://ev-inventory\.com/car/[^']+)'", block)
            if not url_match:
                url_match = re.search(r'href="(https://ev-inventory\.com/car/[^"]+)"', block)
            if not url_match:
                continue
            url = url_match.group(1)
            car_id = url.split("/")[-1]

            # tytul (model + rok)
            title_match = re.search(r"<h2[^>]*>.*?<a[^>]*>(.*?)</a>", block, re.DOTALL)
            title = re.sub(r"<[^>]+>", " ", title_match.group(1)).strip() if title_match else ""
            title = re.sub(r"\s+", " ", title).strip()

            # rok
            year_match = re.search(r"<small>\s*(\d{4})\s*</small>", block)
            year = int(year_match.group(1)) if year_match else 0

            # cena - szukaj roznych formatow
            price = 0
            price_match = re.search(r"€\s*([\d,.\s]+)", block)
            if price_match:
                price_str = re.sub(r"[^\d]", "", price_match.group(1))
                price = int(price_str) if price_str else 0

            # przebieg
            mileage_match = re.search(r"([\d,.\s]+)\s*(?:km|miles)", block, re.IGNORECASE)
            mileage = mileage_match.group(0).strip() if mileage_match else ""

            cars[car_id] = {
                "id": car_id,
                "url": url,
                "title": title,
                "year": year,
                "price": price,
                "mileage": mileage,
            }
        except Exception as e:
            print(f"  Błąd parsowania bloku: {e}")

    return cars


def fetch_cars():
    all_cars = {}
    offset = 0
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

    while True:
        data = dict(FORM_DATA)
        data["offset"] = str(offset)

        resp = session.post(API_URL, data=data, headers=HEADERS, timeout=20)
        print(f"  Status: {resp.status_code}, offset={offset}")

        if resp.status_code != 200:
            print(f"  Body: {resp.text[:300]}")
            resp.raise_for_status()

        html = resp.text.strip()
        print(f"  Odpowiedź (pierwsze 200 znaków): {html[:200]}")

        if not html or html == "0":
            print("  Brak więcej wyników")
            break

        batch = parse_cars_from_html(html)
        print(f"  Sparsowano aut: {len(batch)}")

        if not batch:
            break

        all_cars.update(batch)
        offset += len(batch)

        # ev-inventory nie zwraca total, wiec sprawdzamy czy dostalismy pelna strone
        if len(batch) < 10:
            break

    return all_cars


def get_price(car):
    return car.get("price") or None


def get_car_url(car):
    return car.get("url", "https://ev-inventory.com/for-sale/Netherlands/M3/CPO/")


def format_car_info(car):
    title = car.get("title", "Tesla Model 3")
    mileage = car.get("mileage", "")
    info = title
    if mileage:
        info += f" · {mileage}"
    return info


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
    print(f"  Filtr: 2018-2021, max €20000, Holandia")

    current_cars = fetch_cars()
    print(f"Aut łącznie: {len(current_cars)}")

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
