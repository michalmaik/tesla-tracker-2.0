# Tesla CPO Monitor 🚗

Automatyczne powiadomienia na Discord o nowych Teslach Model 3 CPO w Holandii.

## Co robi?
- Co 15 minut sprawdza oferty na ev-inventory.com
- Wysyła powiadomienie Discord gdy pojawi się **nowe auto**
- Wysyła powiadomienie Discord gdy **cena spadnie**

## Setup (5 minut)

### 1. Sklonuj / sforkuj repo

### 2. Dodaj Discord Webhook jako secret
1. Discord → kanał → Edytuj kanał → Integracje → Webhooki → Nowy webhook → Kopiuj URL
2. GitHub repo → Settings → Secrets and variables → Actions → **New repository secret**
   - Name: `DISCORD_WEBHOOK`
   - Value: `https://discord.com/api/webhooks/...`

### 3. Włącz GitHub Actions
Wejdź w zakładkę **Actions** w repo i kliknij "I understand my workflows, go ahead and enable them".

### 4. Uruchom ręcznie (test)
Actions → "Tesla CPO Monitor" → **Run workflow**

## Struktura plików
```
.github/
  workflows/
    monitor.yml     # harmonogram i kroki
monitor.py          # główny skrypt
cars_state.json     # stan (generowany automatycznie, nie commituj)
```

## Parametry wyszukiwania
Edytuj `PARAMS` w `monitor.py` żeby zmienić filtry (rok, zasięg, cena max itp.)
