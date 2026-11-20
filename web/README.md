# Vejret — WeatherDatalogger web

Dansk vejr-website i Apple Weather-stil, der viser live data fra egen vejrstation (via [WeatherDatalogger API'et](../weatherdatalogger/api/)) og prognose fra Open-Meteo. Ingen lokationsvalg — siden viser kun stationen i Gundsømagle.

```
Browser ──► Caddy (weather-web LXC)
              ├─ /                → statisk build (/var/www/weather/current)
              └─ /api/v1/{current,forecast,history,daily,ws/current}
                                  → WeatherDatalogger API (datalogger-LXC:8000)
                                    Caddy tilføjer X-API-Key — nøglen kommer aldrig i browseren
```

**Stak:** Svelte 5 (runes) + TypeScript + Vite, SunCalc (sol/måne), uPlot (grafer, fase 4). Statisk build, ingen Node-proces i drift.

## Faser

| Fase | Indhold | Status |
|---|---|---|
| 1 — Struktur | API-endpoints (`/forecast`, `/history`, `/daily`, WS header-auth), datalag (WebSocket + REST-fallback, forecast-polling), da-DK formatering, design-tokens, responsivt grid, popup-skal, LXC/deploy | ✅ |
| 2 — Hovedside | Hero med kompakt header ved scroll, animeret himmel (skyer, regn, sne, stjerner, lyn, tåge, sol/skumring), vejrtype fra station + prognose, offline/forældet-banner, PWA | ✅ |
| 3 — Widgets | Timeprognose (temp/nedbør/vind-faner, sol-markører), 10-dages med temperaturbjælker, Vind med kompas, Luftkvalitet, Føles som, UV, Sol med solbane, Måne med fase-tegning, Nedbør, Sigtbarhed, Luftfugtighed, Lufttryk med måler, Lyn, Solstråling, Gennemsnit (klimanormal 1991–2020) og Nedbørsradar (DMI) | ✅ |
| 4 — Popups | Fælles vejrforhold-popup (dag-vælger, målingsmenu, graf målt → prognose, opsummering, forklaring). Klar: Timeprognose, 10-dages (åbner valgt dag), Vind, Føles som, Nedbør, Luftfugtighed, Lufttryk, UV-indeks, Solstråling, Sigtbarhed — samt egne popupper for Sol (solbane, dagslængde), Måne (faser, 30-dages kalender), Luftkvalitet (CAQI-skala, 24 t.), Gennemsnit (måneden mod normalen) og Lyn, og Nedbørsradar (animation af de sidste 2 timer, tidslinje, zoom, farveforklaring) | ✅ |

## Struktur

```
web/
├── src/
│   ├── App.svelte               hovedside: Sky + Hero + Grid + popup
│   ├── app.css                  design-tokens (glas-kort, typografi, himmel)
│   └── lib/
│       ├── api/                 types.ts (API-kontrakt), client.ts (fetch/WS, UTC-parsing)
│       ├── stores/              weather.svelte.ts (live + forecast), ui.svelte.ts (åben popup ↔ #hash)
│       ├── components/          Card, Modal, Grid, Hero, Sky, StatusFooter, Icon
│       ├── widgets/registry.ts  ÉN liste over alle widgets: rækkefølge, størrelse, titel, ikon, komponenter
│       ├── widgets/*.svelte     widget-indhold (fase 3)
│       ├── popups/*.svelte      popup-indhold (fase 4)
│       ├── format.ts            da-DK tal/tid/datoer i Europe/Copenhagen
│       ├── i18n/da.ts           tekster: vejrtyper, kompasretninger, Beaufort, UV/CAQI-niveauer, månefaser
│       └── astro.ts             sol/måne for stationens position
├── radar/                       radar_worker.py (DMI HDF5 → PNG), requirements.txt, radar.example.ini
├── deploy/                      Caddyfile, create_lxc.sh, install.sh, deploy.sh, push_from_mac.sh, systemd/
└── dev/seed_dev_db.py           fyld en udviklings-DB med realistiske testdata
```

Ny widget = én linje i `registry.ts` + `widgets/X.svelte` + `popups/X.svelte`. Målinger i vejrforhold-popuppen defineres i `lib/weather/metrics.ts` (kilde i historik og prognose, graftype, tekster).

### Datakilder pr. widget

| Widget | Kilde |
|---|---|
| Timeprognose, 10-dages, Sigtbarhed | Open-Meteo via API'et (`/forecast`); "Nu" og dagens H/L fra stationen |
| Vind, Føles som, Luftfugtighed, Lufttryk, Nedbør (i dag), UV, Solstråling, Lyn | Stationen (`combined_realtime` + `_stats`) |
| Luftkvalitet | AirLink/aqmonitor; sammenligning med i går fra `/daily` |
| Sol, Måne | Beregnet lokalt (SunCalc) |
| Nedbørsradar | DMI's radarkomposit, omsat til billeder af `weather-radar` i containeren (se nedenfor) |
| Gennemsnit | Dagens højeste vs. normal for datoen (±7 dage, 1991–2020) hentet direkte fra Open-Meteos historiske arkiv og cachet i browseren |

### Radar

DMI udgiver radaren som HDF5-filer (ODIM, stereografisk gitter, 500 m, hvert 10. min. pr. scantype) på `opendataapi.dmi.dk` uden API-nøgle. Browseren kan ikke vise dem, så `radar/radar_worker.py` kører som systemd-timer (`weather-radar.timer`, hvert 5. min.) i weather-web-containeren:

1. Henter de doppler-billeder fra de seneste 2 timer, der ikke er lavet endnu (doppler er ~5 min. friskere end fullRange)
2. Læser filen med `pyfive` (ren Python, intet libhdf5) og DMI's skalering fra rodens `what`
3. Farvelægger dBZ via en 256-trins opslagstabel og omprojicerer til et Web Mercator-gitter over `bounds` (projektionen regnes i numpy; opslaget beregnes én gang pr. gitter)
4. Skriver `/var/lib/weather-web/radar/<tid>.png` + `frames.json` (bounds, billeder, regn ved stationen) og sletter billeder ældre end `keep_minutes`

5. **Nowcast** (porteret fra spiken, afprøvet mod regnmåleren): bevægelsen mellem de to nyeste billeder findes med FFT-krydskorrelation af regnfelterne; faste ekkoer (master, møller), der giver ekko i ≥ 80 % af billederne over ~6 t., ignoreres. Ud fra det beregnes regn ved stationen, nærmeste nedbør (afstand og retning), bevægelse (km/t, fra hvilken retning) og **hvornår regnen når stationen** (op til 2 t.). Det nyeste billede flyttes desuden langs bevægelsen til **6 prognosebilleder (+10 … +60 min.)** — `f<tid>+<min>.png`. Tilstand mellem kørslerne ligger i `/var/lib/weather-web/radar-state/` (ikke serveret)

Caddy serverer mappen som `/radar/*`. Nedbør- og radar-widgetten viser fx "Regn ventes om ca. 25 min.", og radar-popuppen afspiller de sidste 2 timer efterfulgt af prognosen for den næste time (stiplet på tidslinjen). Prognosen er ren fremskrivning — byger, der opstår eller opløses, er ikke med. Widgetten lægger det nyeste billede på et [OpenFreeMap](https://openfreemap.org)-vektorkort (Positron om dagen, Dark om natten — ingen API-nøgle) med MapLibre GL. MapLibre (~300 kB gz) indlæses kun sammen med radar-widgetten. Læsning, skalering og projektion er overtaget fra radar-spiken i `briis/pydmi` (branch `spike/radar`).

Indstillinger: `/etc/weather-radar.ini` (oprettes fra `radar/radar.example.ini` ved første deploy). Fejlsøgning:

```bash
systemctl list-timers weather-radar.timer
journalctl -u weather-radar -n 30
cat /var/lib/weather-web/radar/frames.json
```

### Himlen

`lib/weather/scene.svelte.ts` afgør vejrtypen: prognosens type, men stationen vinder, når den selv måler regn (≥ 0,2 mm/t → regn/slud/sne efter temperatur, ≥ 7,6 mm/t → kraftig regn), lyn inden for 15 min eller hård vind. Tid på døgnet (dag/nat/solopgang/solnedgang ±45 min) kommer fra SunCalc. `Sky.svelte` vælger gradient, `WeatherFx.svelte` tegner effekterne på én canvas.

Se alle udseender uden at vente på vejret — tilføj til URL'en:

```
?sky=rainy                    regn
?sky=lightning-rainy&tod=night  torden om natten
?sky=snowy&tod=dusk           sne ved solnedgang
?sky=fog | cloudy | partlycloudy | pouring | snowy-rainy | windy | clear-night
```

## Udvikling (Mac)

```bash
cd web
cp .env.example .env.local     # API_TARGET=http://<datalogger-ip>:8000, API_KEY=<nøgle>
npm install
npm run dev                    # http://localhost:5173 — også fra telefonen på LAN
npm run check                  # svelte-check / TypeScript
```

Vite-proxyen gør det samme som Caddy i drift: `/api/*` sendes videre med nøglen tilføjet.

Uden adgang til produktion: kør MariaDB lokalt, indlæs `../weatherdatalogger/database/*.sql`, kør `python3 dev/seed_dev_db.py --user … --password …`, og start `api_server.py` mod den.

## Drift: weather-web LXC

**1. Opret containeren** (på Proxmox-hosten):

```bash
curl -fsSLO https://raw.githubusercontent.com/briis/WeatherDatalogger/main/web/deploy/create_lxc.sh
IP=192.168.1.215/24 GW=192.168.1.1 bash create_lxc.sh 215 weather-web    # eller uden IP for DHCP
```

Unprivileged Debian 13, 1 vCPU, 512 MB RAM, 4 GB disk, starter ved boot. Hostens `/root/.ssh/authorized_keys` kopieres ind, så din Mac kan SSH'e direkte, hvis dens nøgle står der.

**2. Installér** (i containeren):

```bash
pct enter 215
bash /root/install.sh          # spørger efter API host:port og API-nøgle
```

Installerer Caddy + Node (Debian-pakker), skriver `/etc/weather-web/env` (0640 root:caddy), installerer Caddyfile og laver første build.

**3. Opdatér senere** — vælg én:

| Hvordan | Kommando |
|---|---|
| Fra GitHub (i LXC'en) | `weather-web-deploy` — eller `weather-web-deploy <branch>` for at prøve en PR |
| Direkte fra Mac'en | `web/deploy/push_from_mac.sh root@192.168.1.215` |

Begge lægger et nyt release i `/var/www/weather/releases/` og skifter `current`-symlinket atomisk; de 5 seneste gemmes til rollback. `cat /var/www/weather/current/VERSION.txt` viser, hvad der kører.

**Datalogger-siden:** API'et skal køre (`[api] enabled = true`) og være nåbart fra weather-web på port 8000. `cors_origins` kan forblive tom — browseren taler kun med Caddy (samme origin).

### Senere: adgang fra internettet

Peg et Proxy Host i Nginx Proxy Manager (fx `vejr.briis.com`) på `http://<weather-web-ip>:80` med **Websockets Support** slået til. Caddy kan blive på `:80`. API-nøglen forbliver skjult; Caddy eksponerer kun de seks GET-endpoints ovenfor. Overvej rate limiting i NPM, før siden gøres offentlig.
