import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"

TESLA_URL = "https://www.tesla.com/nl_NL/inventory/used/m3?arrangeby=plh&zip=1012&range=0"

MAX_PRICE = 20000
MIN_YEAR = 2020
MAX_YEAR = 2021


def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--headless=new")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    # wlacz logowanie requestow sieciowych
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)


def fetch_cars():
    all_cars = {}
    driver = get_driver()

    try:
        print(f"  Ładuję stronę Tesla...")
        driver.get(TESLA_URL)
        time.sleep(15)  # czekaj az strona zaladuje i wykona requesty do API

        # sprawdz tytuł strony
        print(f"  Tytuł strony: {driver.title}")

        # próba 1: wyciągnij dane z JS window
        for js_var in ["__INITIAL_STATE__", "tesla", "App", "TeslaFinance"]:
            try:
                data = driver.execute_script(f"return JSON.stringify(window.{js_var})")
                if data and data != "null" and len(data) > 100:
                    print(f"  Znalazłem dane w window.{js_var} ({len(data)} znaków)")
                    parsed = json.loads(data)
                    cars = extract_cars_from_js(parsed)
                    if cars:
                        print(f"  Aut z JS: {len(cars)}")
                        all_cars.update(cars)
                        break
            except Exception:
                pass

        # próba 2: interceptuj logi sieciowe i znajdź inventory API response
        if not all_cars:
            print("  Szukam w logach sieciowych...")
            logs = driver.get_log("performance")
            for log in logs:
                try:
                    msg = json.loads(log["message"])["message"]
                    if msg.get("method") == "Network.responseReceived":
                        url = msg.get("params", {}).get("response", {}).get("url", "")
                        if "inventory" in url and ("results" in url or "api" in url):
                            print(f"  Znaleziono request: {url[:100]}")
                except Exception:
                    pass

        # próba 3: sprawdz source strony czy jest JSON z autami
        if not all_cars:
            print("  Szukam w source strony...")
            page_source = driver.page_source
            # szukaj JSON z VIN
            import re
            vin_matches = re.findall(r'"VIN"\s*:\s*"([A-Z0-9]{17})"', page_source)
            print(f"  VINy w source: {len(vin_matches)}")

            if vin_matches:
                # spróbuj wyciągnąć cały JSON zawierający te VINy
                json_blocks = re.findall(r'\{[^{}]*"VIN"[^{}]*\}', page_source)
                for block in json_blocks[:5]:
                    try:
                        car = json.loads(block)
                        vin = car.get("VIN", "")
                        if vin:
                            year = car.get("Year", 0)
                            price = car.get("InventoryPrice") or car.get("Price") or 0
                            print(f"  Auto: VIN={vin}, rok={year}, cena={price}")
                            if year and (year < MIN_YEAR or year > MAX_YEAR):
                                continue
                            if price and price > MAX_PRICE:
                                continue
                            all_cars[vin] = car
                    except Exception:
                        pass

        # zapisz screenshot do debugowania
        driver.save_screenshot("/tmp/tesla_screenshot.png")
        print("  Screenshot zapisany w /tmp/tesla_screenshot.png")
        print(f"  Source (pierwsze 2000 znaków):\n{driver.page_source[:2000]}")

    finally:
        driver.quit()

    return all_cars


def extract_cars_from_js(data, depth=0):
    if depth > 5:
        return {}
    cars = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("VIN"):
                vin = item["VIN"]
                year = item.get("Year", 0)
                price = item.get("InventoryPrice") or item.get("Price") or 0
                if year and (year < MIN_YEAR or year > MAX_YEAR):
                    continue
                if price and price > MAX_PRICE:
                    continue
                cars[vin] = item
            else:
                cars.update(extract_cars_from_js(item, depth + 1))
    elif isinstance(data, dict):
        if data.get("VIN"):
            vin = data["VIN"]
            year = data.get("Year", 0)
            price = data.get("InventoryPrice") or data.get("Price") or 0
            if not (year and (year < MIN_YEAR or year > MAX_YEAR)) and not (price and price > MAX_PRICE):
                cars[vin] = data
        for v in data.values():
            if isinstance(v, (dict, list)):
                cars.update(extract_cars_from_js(v, depth + 1))
    return cars


def get_price(car):
    return car.get("InventoryPrice") or car.get("Price") or car.get("price") or None


def get_car_url(car):
    vin = car.get("VIN", "")
    return f"https://www.tesla.com/nl_NL/used/{vin}" if vin else "https://www.tesla.com/nl_NL/inventory/used/m3"


def format_car_info(car):
    year = car.get("Year") or car.get("year", "")
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
    print(f"  Filtr: {MIN_YEAR}-{MAX_YEAR}, max €{MAX_PRICE}, Holandia")

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
