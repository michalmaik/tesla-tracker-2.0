import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import requests

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1482315139893170367/M86LvQvzrqIw679r1igJsT74hZ8wQNIaLC9MIqt45RWhE8duomeBmUyD6DcPFrc2tY1C"
STATE_FILE = "cars_state.json"

# Tesla inventory URL - Holandia, Model 3, uzywane, posortowane od najtanszych
TESLA_URL = "https://www.tesla.com/nl_NL/inventory/used/m3?arrangeby=plh&zip=1012&range=0"

MAX_PRICE = 20000
MIN_YEAR = 2020
MAX_YEAR = 2021


def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--headless")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def fetch_cars():
    driver = get_driver()
    driver.set_page_load_timeout(90)
    all_cars = {}

    try:
        print(f"  Ładuję: {TESLA_URL}")
        driver.get(TESLA_URL)

        # czekaj na zaladowanie wynikow
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CLASS_NAME, "results-container"))
        )
        time.sleep(3)  # dodatkowe czekanie na doladowanie wszystkich kart

        # pobierz dane jako JSON z okna przegladarki (Tesla wstrzykuje dane do window)
        inventory_data = driver.execute_script(
            "return window.__INITIAL_STATE__ || window.tesla || null"
        )

        if inventory_data:
            print("  Znaleziono dane w window.__INITIAL_STATE__")
            # przeszukaj strukture danych
            results = []
            if isinstance(inventory_data, dict):
                results = (
                    inventory_data.get("inventory", {}).get("results", [])
                    or inventory_data.get("results", [])
                    or []
                )
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

        # jesli nie ma danych w JS, scrapeuj HTML
        if not all_cars:
            print("  Brak danych JS, scrapuję HTML...")
            car_sections = driver.find_elements(By.CLASS_NAME, "result-header")
            print(f"  Znaleziono {len(car_sections)} sekcji aut w HTML")

            for section in car_sections:
                try:
                    # pobierz cene
                    price_el = section.find_elements(By.CLASS_NAME, "result-purchase-price")
                    price_str = price_el[0].get_attribute("innerHTML") if price_el else ""
                    price = int("".join(filter(str.isdigit, price_str))) if price_str else 0

                    # pobierz rok
                    year_els = section.find_elements(By.CLASS_NAME, "result-basic-info")
                    year_text = year_els[0].text if year_els else ""
                    year = 0
                    for word in year_text.split():
                        if word.isdigit() and len(word) == 4:
                            year = int(word)
                            break

                    # pobierz link
                    link_el = section.find_elements(By.TAG_NAME, "a")
                    url = link_el[0].get_attribute("href") if link_el else ""

                    # filtruj
                    if year and (year < MIN_YEAR or year > MAX_YEAR):
                        continue
                    if price and price > MAX_PRICE:
                        continue

                    # unikalne ID z URL lub tresci
                    car_id = url.split("/")[-1] if url else f"car_{price}_{year}"
                    all_cars[car_id] = {
                        "price": price,
                        "year": year,
                        "url": url,
                        "text": year_text[:100],
                    }
                    print(f"  Auto: rok={year}, cena=€{price}, url={url[:60]}")

                except Exception as e:
                    print(f"  Błąd parsowania sekcji: {e}")

    finally:
        driver.quit()

    return all_cars


def get_price(car):
    return car.get("InventoryPrice") or car.get("Price") or car.get("price") or None


def get_car_url(car):
    url = car.get("url", "")
    if url:
        return url
    vin = car.get("VIN", "")
    return f"https://www.tesla.com/nl_NL/used/{vin}" if vin else "https://www.tesla.com/nl_NL/inventory/used/m3"


def format_car_info(car):
    year = car.get("Year") or car.get("year", "")
    trim = car.get("TrimName", "")
    text = car.get("text", "")
    color_data = [o for o in car.get("OptionCodeData", []) if o.get("Group") == "PAINT"]
    color = color_data[0].get("Name", "") if color_data else ""
    odometer = car.get("Odometer", "")
    odo_unit = car.get("OdometerType", "km")
    parts = [x for x in [str(year), "Model 3", trim, color] if x]
    info = " · ".join(parts) if parts else text
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
