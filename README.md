# Bewerbungsagent

Ein eigenständiger Python-Agent, der den kompletten Bewerbungs-Workflow automatisiert. Er nutzt
die bestehende [`Profil-Datenbank.json`](../02_Profil-und-Assets/Profil-Datenbank.json) als
**einzige Quelle der Wahrheit** und erzeugt daraus massgeschneiderte Bewerbungsunterlagen.

## Wie dieses Repository aufgebaut ist

Dieses Repo enthält den **versionierten Code**. Ausgeführt wird er in einem *Arbeitsordner*
neben den persönlichen Daten — die Codezeilen in der Doku (`cd 04_Agent`) beziehen sich darauf:

```
Bewerbung/2026/
├── 01_Bewerbungen/          # erzeugte Unterlagen (pro Stelle ein Ordner) – nicht im Repo
├── 02_Profil-und-Assets/    # Profil-Datenbank, CV-Vorlagen                – nicht im Repo
└── 04_Agent/                # ← dieses Repo läuft hier
    ├── bewerbungsagent/     # Paket: Suche, Matching, Dokumente, Dashboard
    ├── data/jobs.db         # SQLite, Quelle der Wahrheit (gitignored)
    └── config.json          # persönliche Angaben (gitignored)
```

**Nicht im Repo** (alle gitignored): das Profil mit echten Lebenslaufdaten, die erzeugten
PDFs/DOCX, die Datenbank und die `config.json` mit Wohnadresse und Kontakt. Der Agent ist
dadurch ohne persönliche Daten lauffähig — für einen Testlauf genügt ein eigenes Profil-JSON
nach dem Muster von [`tests/fixtures/profil-demo.json`](tests/fixtures/profil-demo.json).

## Was der Agent kann

1. **Stellensuche** – durchsucht das Web nach passenden Stellenangeboten:
   - **StepStone** (neu, empfohlen): liefert *einzelne* Stellenangebote mit Titel, Firma, Ort
     und Detail-URL direkt von der Jobbörse (kein API-Key).
   - **DuckDuckGo/Bing**: allgemeine Websuche (best-effort, unzuverlässig bei deutschsprachigen
     Job-Queries).
   - **JobSpy** (`python-jobspy`): aggregiert **LinkedIn**, **Indeed** und **Google Jobs** und
     liefert inklusive vollständiger Anzeigenbeschreibung (kein API-Key). LinkedIn funktioniert
     zuverlässig; Indeed (403) und Google Jobs (deprecated) liefern in vielen Umgebungen leer.
     Siehe [ADR-017](docs/DECISIONS.md).
   - **Manueller Import** für selbst gesammelte Anzeigen.
2. **Relevanz-Triage** – verwirft domänenfremde Treffer (Vertrieb, Marketing, Finanzen,
   Gastronomie, Fahren, Pflege, handwerkliche Fertigung) und Studenten-/Praktikumsstellen
   bereits bei der Suche, bevor sie bewertet werden. Regelbasiert und nachvollziehbar
   (`bewerbungsagent/triage.py`); unklare Titel bleiben im Bestand, dort entscheidet der Fit.
3. **Beschreibungs-Fetch** (`fetch`) – lädt die **vollständigen Stellenbeschreibungen**
   (Aufgaben + Anforderungen) über einen echten Headless-Browser (Chromium). StepStone blockiert
   den `requests`-Weg, der Browser rendert die Detailseite aber vollständig — dadurch wird der
   Fit präzise statt nur titelbasiert geschätzt.
4. **Profil-Fitting** – bewertet jede Stelle gegen dein Skill-Profil (Score 0–100,
   Kategorie *hoch/mittel/niedrig*, passende Skills, Begründung).
5. **Dokumentenerstellung** – erzeugt für jede passende Stelle ein auf dich zugeschnittenes
   **Anschreiben** und einen **Lebenslauf** (PDF, wahlweise Deutsch und/oder Englisch).
   Mit `documents.anschreiben_quellen` wird jeder Anspruch im Anschreiben mit **Quelle und
   Zeitraum belegt** (Retrieval-Schicht `bewerbungsagent/rag.py`); mit
   `documents.anschreiben_luecken` werden bestätigte Lücken transparent benannt statt
   verschwiegen. Liegt im Bewerbungsordner eine `Lebenslauf-Tailoring.json`, wird der
   Lebenslauf daraus gebaut (Headline, Profilabsatz, Stations-Bullets, Fähigkeitsgruppen,
   Kernkompetenzen) — Auswahl und Formulierung kommen aus der Profil-Datenbank, unbelegte
   Fachbegriffe werden beim Erzeugen gemeldet (`bewerbungsagent/tailoring.py`).
6. **Dashboard** – interaktives HTML-Dashboard (angelehnt an das alte `00_Dashboard`):
   Suche, Profil-Fit-Filter, Status-Sichtfilter, KPI-Karten, Status- und Wochen-Diagramme,
   sortierbare Tabelle mit **editierbarem Status** und ein-/ausklappbarer Beschreibung —
   Änderungen werden über einen lokalen Server dauerhaft in `data/jobs.db` (SQLite)
   gespeichert.
7. **Ablauf als Graph** (`ablauf`, optional) – dieselben Stufen, aber als
   Zustandsgraph mit Verzweigung: Stellen, deren Titel für die Relevanz-Triage
   nicht reicht, werden gezielt nachgeladen (`fetch --only-unsure`), statt für
   alles einen Browseraufruf zu bezahlen. Der Ablauf macht außerdem sichtbar,
   dass vor dem Versand eine menschliche Entscheidung steht — die Bewertung
   passiert im Dashboard; `--ohne-review` überspringt den Knoten.
   Braucht die optionale Gruppe (`pip install -e ".[graph]"`); ohne sie läuft
   `pipeline` unverändert linear. Siehe [ADR-023](docs/DECISIONS.md).
8. **Alt-Dashboard-Import** – übernimmt den kompletten Inhalt des bisherigen Dashboards
   (`00_Dashboard/Bewerbungs-Dashboard.md` + `dashboard-state.json`): alle Bewerbungen mit
   Status, Profil-Fit, Arbeitsort, Gehalt, Ansprechpartner, Stellenanzeige-URL und
   Dokument-Links.

## Projektstruktur

```
2026/
├── 00_Dashboard/             # Dashboard-Artefakte: dashboard.html + Starter (Windows/Linux)
├── 01_Bewerbungen/           # Bewerbungsordner je Stelle (PDFs)
├── 02_Profil-und-Assets/     # Profil-Datenbank, CV-Vorlagen
├── 03_Recherche/             # Briefings, Stellenanzeigen
└── 04_Agent/
    ├── agent.py              # CLI-Einstieg
    ├── server.py             # Lokaler Dashboard-Server (liefert HTML + speichert Änderungen)
    ├── config.json           # Konfiguration (Pfade, Suchbegriffe, Sprachen, …)
    ├── requirements.txt
    ├── bewerbungsagent/
    │   ├── config.py         # Konfiguration & Pfadauflösung
    │   ├── profile.py        # Profil laden & Schlüsselwörter extrahieren
    │   ├── matching.py       # Fit-Scoring
    │   ├── statuses.py       # Kanonische Statuswerte (6-Stufen-Funnel)
    │   ├── documents.py      # Anschreiben + Lebenslauf (ReportLab-PDF)
    │   ├── tailoring.py      # Stellenbezogene Lebenslauf-Auswahl (JSON im Bewerbungsordner)
    │   ├── dashboard.py      # Template des interaktiven HTML-Dashboards
    │   ├── importer.py       # Import des alten Dashboards
    │   ├── pipeline.py       # Orchestrierung der Schritte
    │   ├── db.py             # SQLite-Persistenz (Provider-/Nutzer-Feldtrennung)
    │   ├── storage.py        # JSON-Persistenz (jobs.json, matches.json)
    │   └── search/           # Such-Provider (StepStone, DuckDuckGo, Bing, JobSpy, Import)
    ├── data/                 # Arbeitsdaten (jobs.db, jobs.json, matches.json, state.json, …)
    └── output/               # Generierte Dokumente (ein Ordner pro Stelle)
```

Code und Dashboard-Artefakt sind getrennt: Der Server läuft in `04_Agent/`, die
erzeugte `dashboard.html` und die Starter liegen in `00_Dashboard/`. Der Pfad steht
in `config.json` unter `dashboard_file`.

## Schnellstart ohne persönliche Daten

Der Agent ist so aufgebaut, dass er **auch ohne echte Lebenslaufdaten** läuft —
für einen Reviewer oder ersten Test genügen zwei Befehle:

```bash
cp config.example.json config.json     # Beispiel nutzt das mitgelieferte Demo-Profil
pip install -e .                       # Basis-Abhängigkeiten (siehe Installation)
python agent.py match                  # Fit-Scoring gegen das Demo-Profil
```

`match` ist der sichere Einstieg: er braucht weder Netzwerk noch Browser.
`search`/`fetch` benötigen zusätzlich `playwright install chromium`; die
Dokument-Erzeugung (`generate`) erwartet eine DOCX-Vorlage oder fällt auf die
eingebaute ReportLab-Vorlage zurück.

## Installation

### Reproduzierbar mit `uv` (empfohlen)

`uv` friert die exakten Versionen in [`uv.lock`](uv.lock) ein — jede Neuinstallation
liefert **garantiert denselben Stand** wie zum Zeitpunkt des Locks.

```bash
# uv einmalig installieren (siehe https://docs.astral.sh/uv):
#   curl -LsSf https://astral.sh/uv/install.sh | sh

cd 04_Agent
uv sync                # installiert die Basis-Abhängigkeiten aus uv.lock
uv sync --extra jobspy # optional: JobSpy (LinkedIn/Indeed/Google) mit installieren
uv run python agent.py search
```

Nach einer Änderung an `pyproject.toml` den Lock aktualisieren: `uv lock`.

### Klassisch mit `pip` (Fallback)

```bash
cd 04_Agent
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Browser für Suche-Beschreibungen (fetch) und den PDF-Export der Karte:
playwright install chromium
```

Optionale Extras: JobSpy (LinkedIn/Indeed/Google) und semantisches Matching sind
bewusst **nicht** in `requirements.txt` enthalten — sie ziehen schwere
Abhängigkeiten (pandas/pydantic bzw. torch). Mit `pip` nachinstallieren:

```bash
pip install -e ".[jobspy]"       # JobSpy-Provider
pip install -e ".[semantic]"     # experimentelles semantisches Matching
```

## Nutzung

```bash
# Einzelschritte
python agent.py import-old     # Inhalt des alten Dashboards übernehmen
python agent.py search          # Web-Suche (StepStone + DuckDuckGo)
python agent.py searches        # gespeicherte Suchen auflisten
python agent.py search "Test & Verification"  # nur eine gespeicherte Suche ausführen
python agent.py fetch           # Vollständige Beschreibungen per Browser laden (Chromium)
python agent.py match           # Präzises Fit-Scoring gegen das Skill-Profil
python agent.py generate --all  # Dokumente für alle passenden Stellen
python agent.py generate --ids 1,2,3   # nur bestimmte Stellen
python agent.py quality         # erzeugte Unterlagen prüfen (Fakten, Pflichtteile, PDF)
python agent.py followup        # fällige Nachfassen anzeigen
python agent.py followup --write  # Follow-up-Texte in die Bewerbungsordner legen
python agent.py providers       # Zustand der Such-Quellen (--enable/--disable/--reset)
python agent.py dashboard       # HTML-Dashboard (neu) erzeugen
python agent.py status          # aktuelle Stellen anzeigen

# Alles in einem Durchlauf
python agent.py pipeline        # Suche → Match → Dokumente → Dashboard
```

Das Ergebnis ist [`dashboard.html`](dashboard.html) (nach dem ersten Lauf) sowie pro Stelle ein
Ordner unter `output/<Firma> - <Stelle>/` mit den PDFs.

## Dashboard öffnen & Status ändern

Das Dashboard ist **interaktiv** (Suche, Filter, Diagramme, sortierbare Tabelle). Um den
Status (oder Kontakt/Notiz/Interview-Termin) **dauerhaft ändern** zu können, starte den
lokalen Server:

```bash
../00_Dashboard/dashboard-oeffnen.sh  # startet den Server (falls nötig) und öffnet das Dashboard
# oder manuell:
python agent.py dashboard
python server.py                # läuft auf http://127.0.0.1:8766/00_Dashboard/dashboard.html
```

Der Server liefert das Dashboard aus und speichert Änderungen über `GET/POST /state` in
`data/jobs.db` (SQLite, Alembic-migriert). `data/state.json` bleibt als abgeleiteter Snapshot
für bisync/Backup bestehen. Ohne Server (direktes Öffnen der `dashboard.html` als Datei)
funktioniert die Anzeige, aber Statusänderungen werden nur lokal im Browser gehalten
(bis der Server läuft).
Über „Ordner ↗“ in der Links-Spalte öffnet der Server den jeweiligen Bewerbungsordner im
Dateimanager.

**Verknüpfung auf dem Desktop (Linux).** Ein `.desktop`-Launcher zeigt auf das Skript;
ein reiner Symlink auf die `.sh` genügt nicht, weil der Dateimanager ihn sonst im
Editor öffnet. Das Skript muss ausführbar sein (`100755`), sonst bricht der Klick mit
„Keine Berechtigung“ (Exit 126) ab:

```bash
chmod +x dashboard-oeffnen.sh
cat > ~/Schreibtisch/bewerbungs-dashboard.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Bewerbungs-Dashboard
Exec=/pfad/zu/00_Dashboard/dashboard-oeffnen.sh
Icon=applications-office
Terminal=false
EOF
chmod +x ~/Schreibtisch/bewerbungs-dashboard.desktop
gio set ~/Schreibtisch/bewerbungs-dashboard.desktop metadata::trusted true
```

Unter Windows übernehmen `dashboard-oeffnen.bat` und `dashboard-oeffnen.ps1` dieselbe
Aufgabe.

## Täglicher Lauf (automatisch)

Damit die Stellen und Unterlagen jeden Tag aktuell vorliegen, läuft der Ablauf
automatisch — per **systemd-User-Timer**, ohne Cloud (Begründung:
[ADR-024](docs/DECISIONS.md)).

```bash
# Einmalig einrichten (Units liegen im Repo unter docs/systemd/)
cp docs/systemd/bewerbungsagent-tageslauf.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bewerbungsagent-tageslauf.timer

# Prüfen
systemctl --user list-timers bewerbungsagent-tageslauf.timer
```

Der Timer feuert **täglich 12:00** (plus Streuung bis 5 min) und holt einen
verpassten Lauf nach, wenn der Rechner aus war (`Persistent=true`) — so fällt
kein Tag aus.

Der Lauf macht dasselbe wie `agent.py ablauf`, aber mit `--beschreibung alle`:
vollständige Anzeigentexte für einen präzisen Fit, nicht nur für unklare Titel.

**Ergebnis prüfen:**

```bash
cat data/tageslauf-status.json     # { "zustand": "OK" | "FEHLER" | "LAUFEND", ... }
tail -40 data/tageslauf.log        # Verlauf des Laufs
```

Läuft der Lauf, während der Google-Drive-Sync (bisync, alle 15 min) dazwischen
greift, darf er nicht das offene Log verlieren. Die Laufzeitdateien
(`tageslauf.log`, `-status.json`, `.lock`) sind deshalb in
`~/.config/rclone/bisync-exclude.txt` ausgenommen — am 19.10. löschte bisync das
offene Log, der Prozess schrieb danach in eine verschwundene Datei
(`/proc/<pid>/fd/1 → tageslauf.log (deleted)`).

Die Stellen, die der Lauf neu gefunden hat, tragen im Dashboard das Badge
**„neu gefunden"** (Filter: „Nur neu gefundene"). Sie bleiben markiert, bis ein
Lauf neue Stellen mitbringt — ein Lauf ohne Funde löscht das Label nicht. Sie
erscheinen auch ohne Unterlagen, damit das Label sichtbar ist; ein Hinweis nennt,
wie viele Funde ausserhalb der Pendelgrenze liegen. Details:
[ADR-025](docs/DECISIONS.md).

Von Hand auslösen: `systemctl --user start bewerbungsagent-tageslauf.service`
oder direkt `scripts/tageslauf.sh`.

## Agenten-Map (was der Agent tut)

Eine eigenständige Übersichtsseite zeigt in einer einzigen HTML-Datei, **was der Agent
macht, was er kann und wo er was verarbeitet**:

```bash
python scripts/build_agent_map.py            # → output/agent-map.html
python scripts/build_agent_map.py --pdf      # zusätzlich → output/agent-map.pdf
python scripts/build_agent_map.py --pdf --pdf-format hoch   # PDF hochkant
```

Die Karte dient auch als Arbeitsnachweis. Für eine Bewerbung ist das PDF
praktischer als die HTML, weil es sich anhängen und überall öffnen lässt.
Standard ist **Querformat**: Die Karten sind 1180 px breit und würden hochkant
auf 632 px verkleinert (Ortslabels ~4,4 pt statt ~6,7 pt).

Enthalten sind:

- **System-Map** — klickbares Ablaufdiagramm (Quellen → vier Stufen → Ausgabe) mit
  Dienste-Schicht; jeder Knoten erklärt Eingang und Ausgang.
- **Geografie-Map** — echte Koordinaten der Stellen aus dem Geocode-Cache, Mittelpunkt
  ist der Wohnort, Linien zeigen den Pendelweg, gefärbt nach Fahrzeit.
- **Befehle, Ablageplan, Dienste und Module** mit Verantwortung und Reichweite
  (Netzwerk vs. deterministisch).

Die Seite ist offline nutzbar (keine externen Bibliotheken) und liest die Zahlen direkt
aus `data/jobs.db`.

## Stellensuche & manueller Import

Die freie Websuche ist bewusst **pluggable**:

- **StepStone** (Standard) liefert einzelne Stellenangebote. Die **Detailseiten** blockieren
  zwar den `requests`-Weg, aber `python agent.py fetch` lädt die vollständigen Beschreibungen
  über einen echten Headless-Browser (Chromium) — damit wird das Fit-Scoring präzise.
  Erkennt der Fetcher eine abgelaufene Anzeige, setzt er `verfuegbar: False`
  (Badge „abgelaufen" im Dashboard). Weil die Seite als kompletter Seitentext gelesen wird und
  Jobbörsen darauf fremde Anzeigen auflisten, sind die Muster bewusst kontextgebunden. Nach einer
  Änderung an den Mustern die alten Flags neu bewerten:

  ```bash
  python scripts/recheck_expired.py            # Probelauf: nur prüfen
  python scripts/recheck_expired.py --apply    # Korrekturen speichern
  ```
- **ATS** (Standard seit 10/2026) fragt die Karriereseiten der Zielunternehmen **direkt** ab:
  Greenhouse, Lever, Ashby, Workday, Eightfold und SuccessFactors haben öffentliche Endpunkte —
  kein Scraping, keine Blockade. Die Board-Liste wird automatisch aus bereits vorhandenen
  Anzeigen abgeleitet (Greenhouse/Lever/Ashby), kann aber in `search.ats_boards` fest vorgegeben
  werden.
  - **Greenhouse/Lever/Ashby** liefern den **vollständigen Anzeigentext** mit — für diese
    Stellen entfällt der Browser-Fetch.
  - **Workday** (`tenant` + `site`) liefert Titel, Ort und URL, aber **keinen** Beschreibungstext —
    der liegt als `ld+json` auf der Detailseite und wird über `python agent.py fetch` nachgeladen.
    Der Index wird parallel paginiert, weil einzelne Konzerne mehrere tausend Stellen führen.
  - **Eightfold** (`host` + `domain`) ist das ATS von Qualcomm, Infineon u. a.; der öffentliche
    Index `/api/pcsx/search` filtert serverseitig nach `location` (Standard `munich`).
  - **SuccessFactors „Jobs2Web"** (`host`) hat keinen JSON-Endpunkt: die Stellen liegen als
    HTML-Tiles in `/tile-search-results/` und werden geparst (HENSOLDT, 25 pro Seite).
  - **SmartRecruiters** (`company`, optional `city`/`country`) liefert den **vollständigen
    Anzeigentext** über die Detail-URL (`jobAd.sections`) — kein Browser-Fetch nötig (Renesas).
  - **Oracle Cloud HCM** (`host` + `site`, optional `location`) ist das System von Texas
    Instruments; der Index liefert 25 Stellen pro Aufruf, den Text holt der Browser-Fetch.
  - **TYPO3-Jobbörse** (`list_url`) ist die eigene Jobbörse von MTU Aero Engines: alle
    Stellen auf einer Seite, Eckdaten als `data-*`-Attribute, Volltext als `ld+json` auf der
    Detailseite — ohne Browser. Die Detailseiten werden nur für die Stellen geladen, die den
    Ortsfilter passieren (rund 190 von 400).
  - **Sitemap** (`sitemap`, optional `url_must_contain`, `max_jobs`) ist der generische Weg für
    Karriereseiten ohne ATS-API, die aber eine `sitemap.xml` mit den Anzeigen-URLs ausliefern.
    Jede Detailseite wird gelesen und das `JobPosting`-JSON-LD ausgewertet (Titel, Arbeitgeber,
    Ort, Volltext). Live verifiziert an **E.ON** (`jobs.eon.com`, Anbieter „4suxess"):
    `careers.eon.com` rendert die Liste nur per JavaScript, `/api/*` ist im `robots.txt`
    gesperrt und ein Ortsfilter per URL existiert nicht — die Sitemap dagegen listet alle 502
    Anzeigen, der Ort steht im Slug. `url_must_contain` grenzt **vor** dem Laden der
    Detailseiten ein (9 statt 502), sonst würde jede Anzeige einzeln geholt. Zwei Eigenheiten:
    Der Arbeitgeber kommt aus dem JSON-LD, nicht aus `firma` — unter „E.ON" würden sonst die
    Konzerntöchter verschwinden (`E.ON Drive Germany GmbH`, `E.ON Digital Technology GmbH`, …).
    Und die Sitemap ist **unvollständig/veraltet**: 4 der 9 München-URLs antworteten mit 404 und
    werden übersprungen, ohne den Lauf abzubrechen.
- **Arbeitnow** ist eine kostenlose Job-Board-API ohne Schlüssel (`search.arbeitnow_pages`,
  Standard 3). Sie liefert 300 Stellen pro Seite **ohne serverseitigen Filter** — der Ort wird
  lokal gefiltert, und es kommt nur eine Kurzfassung mit, der Volltext muss per `fetch` nach.
- **XING** (`xing`) und **Indeed** (`indeed`) rendern ihre Treffer nur im Browser und werden
  deshalb mit Headless-Chromium gelesen (`search/browser.py`). Beide bekommen die ganze
  Begriffsliste in **einer** Sitzung, weil jeder Browserstart ~1 s kostet; über
  `search.xing_terms` / `search.indeed_terms` lässt sich die Liste eingrenzen.
  - **XING** antwortet per HTTP 200, aber das HTML enthält **keine** Anzeige (reine
    JS-Hülle): kein RSS, keine offene JSON-API, GraphQL-Introspection in Produktion gesperrt.
    Firma und Ort werden **relativ zum Titel** aus dem Kartentext gelesen — davor steht
    optional ein Badge („Urgently hiring"), eine Suche nach „erste Zeile in Title-Case"
    machte daraus „Dringend gesucht" als Ort. Der Volltext steht in
    `[data-testid="expandable-content"]` und ist sofort vollständig („Show more" ändert nur
    die Anzeige). Paginierung über „Show more", 20 Treffer je Klick.
  - **Indeed** beantwortet einfache HTTP-Anfragen mit Cloudflare-HTTP 403 — auch die alte
    RSS-Schnittstelle und `python-jobspy`. Im Browser lädt die Liste; der Consent-Hinweis muss
    weggeklickt werden. Die Trefferliste enthält **keinen** Anzeigentext, und direkte
    `/viewjob?jk=…`-Aufrufe enden nach wenigen Anfragen in „Sign In" oder im Cloudflare-Check
    (im Test 0 von 3). Der Text wird deshalb über den **Klick auf den Titel** geholt: das
    öffnet die Master-Detail-Ansicht (`…&vjk=<jk>`), die auf der Trefferliste bleibt — im
    Test 3 von 3 mit Volltext.
- **jobs.labo.de** (`labo`) ist eine Fach-Jobbörse (Medizin/Labor/Technik) mit serverseitig
  gerendertem HTML, kein Browser nötig. Suche über `/suchergebnis?jsjr=<Begriff>&jsjo=<Ort>`;
  jede Anzeige ist ein `div.jwtpl-hili-item`. Drei Eigenheiten: Bei `itemCompany` stehen
  `data-*`-Attribute **vor** `class` (ein Regex auf `class` direkt nach dem Tag-Namen findet
  die Firma nicht), Titel enthalten weiche Trennzeichen (`&shy;`), und die Detailseite hat
  **kein** JSON-LD — der Text steht in `div.jwtpl-jobaded-dataTextField`-Blöcken. Die
  Folge-Seite muss über die Knopf-URL geladen werden (sie enthält eine Sitzungs-ID).
- **JobLeads** (`jobleads`) liefert die Trefferliste serverseitig gerendert, ohne Login: jede
  Stelle ist eine `div.search-job-card` mit `data-testid`-Markern für Titel, Firma, Gehalt und
  Datum, der Ort steckt im Slug der Anzeigen-URL (`…--munchen--hash`). Die Detailseite enthält
  den Volltext als `JobPosting`-JSON-LD (`id="jobPostingLdjson"`) — der Browser-Fetch entfällt.
  Anders als bei den ATS-Quellen ist die Firma **der Arbeitgeber aus der Anzeige**, nicht der
  Aggregator, sonst landen alle Treffer unter einem Namen. Einschränkungen (alle live geprüft):
  - **25 Karten pro Anfrage** — `page=2`, `start=25`, `offset=25`, `currentPage`, `p`, `spage`
    und `pageIndex` werden ignoriert, es kommt stets dieselbe erste Seite. Mehr Treffer gibt es
    nur über **mehr Suchbegriffe** (`jobleads_searches`) oder einen Browser mit Scrollen; die
    gespeicherte Seite einer Browser-Sitzung enthielt 177 Karten. Weil das Fenster nur 25 Karten
    breit ist, entscheidet die **Wortwahl** über die Abdeckung: `Test Engineer` fand eine Stelle
    3/3 Läufe, `System Test Engineer` nur 1/3 — breitere Begriffe decken mehr ab.
  - **HTTP 429 (Cloudflare)** bei Bursts: 177 Detailseiten mit 6 Threads → nur 80 Volltexte.
    Der Provider holt deshalb mit 3 Threads und bis zu 4 Versuchen mit Backoff.
  - `minSalary` ist **keine** harte Grenze (bei `minSalary=80000` kamen weiterhin
    60.000–80.000 durch), sondern verschiebt nur das Ranking — bleibt standardmäßig aus.
  - Die Firma stammt aus der Anzeige und ist **nicht immer der Arbeitgeber**: bei
    Aggregator-Anzeigen steht dort teils die Quellbörse („Free resume", „Devopsroles",
    „Itsicherheit Online") oder die Anzeige erscheint mehrfach. Das JSON-LD wiederholt nur
    denselben Namen, liefert also keine Korrektur.
  - Die Treffer überlappen stark mit StepStone/JobSpy — deshalb ist der Provider nicht
    voreingestellt.

- **DuckDuckGo** und **Bing** sind seit 10/2026 **nicht mehr voreingestellt**: live geprüft
  lieferte DuckDuckGo 0 Treffer, Bing ausschließlich `bing.com/ck/a`-Redirects zu
  branchenfremden Firmen. Die Module bleiben für den Fall, dass sich das ändert; für
  Stellensuche braucht es stattdessen eine bezahlte Such-API (Brave/Adzuna) mit Schlüssel.
- **JobSpy** aggregiert LinkedIn/Indeed/Google Jobs inklusive Beschreibung; läuft auf den ersten
  `jobspy_max_terms` (Standard 4) Suchbegriffen, weil es langsam ist und verwandte Begriffe
  stark überlappen. Optional installieren: `pip install -e ".[jobspy]"`. Indeed antwortet
  derzeit durchgehend mit 403, Google Jobs ohne Daten, LinkedIn mit 429 — der Provider ist
  stark limitiert. Die **Bundesagentur-API** (`rest.arbeitsagentur.de`) antwortete im Test
  ebenfalls mit 403 und ist deshalb nicht eingebaut.

### Gespeicherte Suchen

Statt immer alle `search.query_terms` durchzugehen, kannst du **benannte Suchen** definieren
und einzeln starten. Lege dazu `data/saved_searches.json` an:

```json
[
  {
    "name": "Test & Verification",
    "query_terms": ["Testingenieur", "ADAS Test", "HiL Test Engineer"],
    "location": "München",
    "providers": ["stepstone", "jobspy"]
  },
  {
    "name": "Embedded",
    "query_terms": ["Embedded Test", "E/E Integration", "Systemingenieur"],
    "location": "München",
    "providers": ["stepstone"]
  }
]
```

- `python agent.py searches` listet alle gespeicherten Suchen.
- `python agent.py search "Test & Verification"` führt nur diese aus.
- Ohne Datei existiert automatisch eine „Standard"-Suche aus `config.json`.
- Der manuelle Import (`data/import_jobs.json`) läuft unabhängig von der gewählten Suche immer mit.

Manueller Import: Lege `data/import_jobs.json` an (Format siehe
[`data/import_jobs.example.json`](data/import_jobs.example.json)) — diese Einträge werden
immer mit durchsucht und gematcht. Für einen schnellen Offline-Test ohne Internet:

```bash
cp data/sample_jobs.json data/jobs.json
python agent.py match
python agent.py generate --all
python agent.py dashboard
```

## Matching

Das Fit-Scoring (`bewerbungsagent/matching.py`) ist transparent und deterministisch:

- **Phrasen-Treffer im Titel** zählen am stärksten (6 Punkte je Treffer),
- **Phrasen-Treffer im Anzeigentext** (4 Punkte),
- **Inhaltswort-Überschneidung** (2 Punkte),
- **Standort-Bonus** (+10, wenn der Ort zum Suchort passt).

Deutsch/englische Varianten werden über eine Synonym-Brücke zusammengeführt („Testautomatisierung“
matcht auch „test automation“/„testautomation“). Kategorien: `hoch` ≥ 65, `mittel` ≥ 40, sonst
`niedrig`.

Zusätzlich bewertet `bewerbungsagent/dimensions.py` dieselbe Stelle in sieben Dimensionen
(Kompetenz, Aufgaben, Seniorität, Technologie/Branche, Gehalt, Arbeitsmodell, Entwicklung) —
**berichtend**: Der Fit-Wert bleibt der Keyword-Score, die Dimensionen erscheinen im Dashboard
als „Dim NN %“ und dienen der Diagnose. Hart ist nur die K.O.-Liste (Anzeigen-Gehalt unter
`matching.dimensions.ko_gehalt_min_tsd`), sie blockiert die automatische Unterlagenerzeugung.
Details: `docs/ARCHITECTURE.md`, ADR-031.

Aus dem Fit folgt der Status — die Grenzen stehen in `bewerbungsagent/pipeline.py`:

| Fit | Status | Dokumente |
|---|---|---|
| < 50 % | ausgeblendet | – |
| 50–70 % | `Research` (Filter hält 65–70 % bzw. Pendelweg knapp drüber; 50–64 % wird verborgen) | keine |
| > 70 % | `Dokumente erstellt` | ja |

Ein Anschreiben für einen 55-%-Treffer kostet Zeit und geht fast nie durch — deshalb
bekommt das mittlere Band nur den Status `Research`. Bereits erzeugte Unterlagen in
diesem Band setzt der nächste `enrich`-Lauf auf `Research` zurück; die Dateien bleiben
liegen. Versendete und abgeschlossene Bewerbungen bleiben unangetastet.

Research-Funde erscheinen **nur mit Unterlagen** in der Dashboard-Tabelle — das ist die
Entscheidungsgrundlage „lohnt sich eine Bewerbung?". Eine pauschale Lockerung wäre kein
Gewinn: im Live-Bestand liegen 658 Einträge im Status `research`/`neu` ohne Unterlagen
(bestimmt am 23.10.2026). Für bewusst beobachtete Kandidaten gibt es deshalb die
ausdrückliche Freigabe:

```json
{ "key": "https://…", "status": "research", "research_sichtbar": true }
```

`research_sichtbar` wirkt nur bei Status `research`, hebt die Pendelzeit-Grenze **nicht**
auf und ist ein Nutzerfeld (`db.USER_FIELDS`) — ein Suchlauf kann es nicht
überschreiben. Die Zeile steht dann mit Badge `Research` in der Tabelle, die der
Status-Schalter „Research einblenden" ein- und ausblenden kann.

Die Schwelle (`documents.min_fit_for_generation`: `hoch` = > 70 %, `mittel` = 50 %,
`niedrig` = 0 %) lässt sich in `config.json` anpassen und gilt für beide Wege —
`generate` und die automatische Erzeugung in `enrich`.

Unabhängig vom Fit werden **Studenten-/Praktikumsstellen** und **Technikerrollen**
(„Techniker", „Systemtechniker", „Technician") ausgeblendet: beides sind keine
Ingenieursstellen. Eine *abgeschlossene* Bewerbung (`sent`/`followup`/`interview`/
`rejected`) auf eine solche Stelle bleibt als echter Verlauf sichtbar.

## Konfiguration

Alle Einstellungen stehen in [`config.json`](config.json):

- `profile_json` – Pfad zur Profil-Datenbank (Standard: die bestehende Datei).
- `search.query_terms` / `search.location` / `search.providers` – Suchbegriffe, Ort, Provider
  (verfügbar: `manual`, `stepstone`, `jobspy`, `ats`, `arbeitnow`, `jobleads`, `xing`,
  `indeed`, `labo`, `duckduckgo`, `bing`).
- `search.xing_terms` / `search.indeed_terms` – eigene Begriffslisten für die beiden
  Browser-Provider (Standard: `search.query_terms`). Sinnvoll, weil jeder Begriff dort einen
  Seitenaufruf plus bis zu 25 Detailseiten kostet.
- `search.xing_max_results` / `search.indeed_max_results` – Obergrenze je Lauf (Standard 25).
- `search.labo_max_jobs` – Obergrenze für jobs.labo.de (Standard 120).
- `search.ats_boards` – Karriereseiten für die ATS-Abfrage. Greenhouse/Lever/Ashby nutzen
  `board`, Workday `tenant`+`site`, Eightfold `host`+`domain`, SuccessFactors „Jobs2Web" nur
  `host`, SmartRecruiters `company`, Oracle Cloud `host`+`site`, TYPO3 `list_url`. Für
  `ats: "sitemap"` gilt `sitemap` (Pflicht) plus optional `url_must_contain` und `max_jobs`.
  Leer = Greenhouse/Lever/Ashby automatisch aus den vorhandenen Anzeigen ableiten.
- `search.ats_only_near_munich` – nur Stellen aus der Münchener Metropolregion übernehmen
  (Standard `true`); verhindert teure Geocoding-Aufrufe für weltweite Stellen.
- `search.arbeitnow_pages` – Seiten der Arbeitnow-API (Standard 3, je 300 Stellen).
- `search.jobleads_searches` – JobLeads-Suchen (Standard `[]`). Ein Eintrag ist entweder ein
  Suchbegriff (die URL wird samt München-Koordinaten gebaut) oder ein Objekt mit fertiger
  `list_url`, optional `max_jobs` und `with_description`. Ist die Liste **leer**, greift der
  Provider auf `search.query_terms` zurück (begrenzt über `jobleads_max_terms`, Standard 6) —
  eine leere Liste ist eine vergessene Pflege, keine Abschaltung, und hat schon einmal dazu
  geführt, dass Stellen derselben Trefferliste nie gefunden wurden.
- `search.jobleads_max_terms` – Obergrenze für diesen Rückfall (Standard 6). Jede Suche kostet
  eine Listenseite plus bis zu 25 Detailseiten; JobLeads drosselt mit HTTP 429.
- `search.jobleads_min_salary` – `minSalary` in der Such-URL (Standard `0` = aus). Filtert bei
  JobLeads **nicht** hart, verschiebt nur das Ranking.
- `search.jobspy_max_terms` – Anzahl der Suchbegriffe, auf denen der JobSpy-Provider läuft
  (Standard 4).
- `search.triage` – Relevanz-Triage an/aus (Standard `true`). Domänenfremde Treffer  (Vertrieb, Marketing, Finanzen, Gastronomie, Fahren, Pflege, handwerkliche Fertigung)
  werden schon bei der Suche verworfen, statt erst später gelöscht zu werden. Verworfene
  Treffer werden zur Nachvollziehbarkeit in `data/triage_rejected.json` protokolliert.
  Unklare Titel bleiben im Bestand — dort entscheidet der Fit.
- `search.triage_reject` / `search.triage_keep` – Nutzerentscheidungen als Liste von
  Titel-Fragmenten (Teilstring, Groß-/Kleinschreibung egal). Nötig für Restfälle, die ein
  Regelwerk nicht prinzipiell entscheiden kann: „Sales Manager **Embedded**" nennt Technik,
  meint aber Vertrieb. Statt dafür Wörter anzuhäufen, entscheidet der Nutzer — dauerhaft
  und nachvollziehbar. `triage_keep` gewinnt gegen `triage_reject` und gegen alle Regeln,
  damit eine zu breite Reject-Regel nie eine echte Stelle verliert.
  Mit `|` lässt sich eine Regel an die Firma binden: `"Teamleitung | VITES"` trifft nur
  diese Stelle, nicht jede „Teamleitung Vertrieb".
- `max_pendelzeit_min` – Obergrenze des Pendelwegs in Minuten (Standard 30). Zu weit
  entfernte Stellen werden gar nicht erst angelegt: keine Unterlagen, kein Eintrag im
  Dashboard. Unbekannte Pendelzeiten (z. B. Remote) sind kein Ausschlussgrund.
- `research_filter` – begrenzt den `research`-Bestand. Behalten werden nur Funde mit
  Fit zwischen `fit_min` und `fit_max` (Standard 65–70 %) oder mit Pendelweg bis
  `max_pendelzeit_min + commute_grace_min` (Standard 40 min). Funde **oberhalb**
  des Fensters sind keine Research-Fälle mehr, sondern Dokumenten-Kandidaten und
  werden nicht gelöscht. Alles andere wird nur als `deleted` markiert (nichts wird
  gelöscht) und bei jeder Neubewertung erneut geprüft — verbessert sich der Fit,
  kommt die Stelle zurück. Stellen mit Unterlagen bleiben immer erhalten.
  `"enabled": false` schaltet den Filter ab.
- `commute.home_address` – Ausgangspunkt für die Pendelweg-Berechnung. Bewusst **nicht** im
  Quelltext, sondern hier (bzw. in der privaten `config.json`).
- `commute.contact_email` – Kontakt für die Nominatim-/OSRM-Anfragen; leer lassen genügt
  (dann nennt der User-Agent nur die Projekt-URL).
- `commute.office_overrides` – Firmensitz je Arbeitgeber, wenn die Anzeige nur die
  Zentrale nennt: `{"STARK Defence": "Maisach"}`. Der Wert ersetzt die Ortsangabe der
  Stelle, und der Pendelweg wird zum echten Büro berechnet. Ohne Überschreibung wird
  der Weg zu kurz geschätzt (München-Zentrale statt Maisach) und eine zu weit entfernte
  Stelle kann die `max_pendelzeit_min`-Grenze umgehen.
- `documents.languages` – erzeugte Sprachen (`["de", "en"]`).
- `documents.accent_color` – Akzentfarbe der PDFs.
- `documents.min_fit_for_generation` – Mindest-Fit für die automatische Erstellung
  (`hoch` = > 70 %, Standard; `mittel` = 50 %; `niedrig` = 0 %).
- `documents.anschreiben_quellen` – `true`: belegt jeden Anspruch im Anschreiben mit
  Quelle und Zeitraum (siehe `bewerbungsagent/rag.py`). Standard `false`.
- `documents.anschreiben_luecken` – `true`: benennt im Anschreiben transparent die
  bestätigten Lücken, die für *diese* Stelle relevant sind (z. B. DO-178C bei einer
  Verteidigungs-Stelle). Standard `false`.
- `documents.lebenslauf_vorlage` – eigene DOCX-Vorlage (`{"de": …, "en": …}`); nur der
  Profil-Absatz wird pro Stelle ersetzt.

## Hinweise

- **Google Drive**: Beim Betrieb direkt im synchronisierten Google-Drive-Ordner können bei sehr
  schnellen, mehrfachen Schreibvorgängen Sync-Konflikte (`*.conflict*`-Dateien) entstehen. Falls
  das auftritt, `data/` und `output/` auf ein lokales Laufwerk legen (Pfade in `config.json`).
- Die PDFs nutzen eingebaute Helvetica-Schriften und benötigen keine Font-Dateien.
- Lebenslauf-Inhalte stammen vollständig aus der Profil-Datenbank – vor der Generierung lohnt ein
  Blick in deren `tailoring_notes`, um die Positionen passend zu gewichten.

## Entwicklung

### Tests

```bash
python -m pytest          # alle Tests
python -m pytest --cov    # mit Coverage
```

Die Tests laufen gegen ein **anonymisiertes Demo-Profil**
(`tests/fixtures/profil-demo.json`) — es werden keine echten Personendaten
benötigt, und es gehen keine in Logs/CI.

Getestet werden die deterministischen Kerne: `profile` (Keyword-Extraktion),
`matching` (Fit-Scoring) und `dashboard` (Datumslogik). Für jeden historisch
aufgetretenen Fehler existiert ein Regressionstest; ein Mutationstest
(Bug absichtlich wieder einbauen) bestätigt, dass die Tests greifen.

### Evaluation (Modellqualität)

Neben den Unit-Tests gibt es eine **Offline-Evaluation** des Fit-Scorings
gegen die echten Bewerbungsentscheidungen:

```bash
python -m eval.run_eval --out eval/report.md
```

Sie liefert Precision/Recall/F1, einen Threshold-Sweep und eine
Majority-Baseline.

**Zuerst Labels setzen** — der `status` im Bestand ist ein *Prozess*-Signal
und **kein Eignungsmaß** (ADR-012):

```bash
python -m eval.label_tool --limit 25    # j/n/s je Stelle → eval/labels.csv
python -m eval.run_eval --out eval/report.md
```

Ohne manuelle Labels gibt das Skript **kein** Ergebnis aus, sondern weist auf
die fehlende Ground Truth hin. Das ist Absicht: eine plausible Zahl ohne
belastbare Labels wäre irreführend.

**Vergleich mit semantischem Matching** (Embeddings, optionales Extra
`[semantic]`):

```bash
python -m eval.run_semantic_eval --model intfloat/multilingual-e5-base
```

**Vergleich mit Cross-Encoder-Reranking:**

```bash
python -m eval.run_rerank_eval --model BAAI/bge-reranker-base
```

**Ergebnis: Beide neuronalen Verfahren verlieren** (ADR-015, ADR-016).
Auf den harten Fällen (technische, aber unpassende Stellen):

| Verfahren | AUC | Kosten |
|---|---:|---|
| **Keyword-Fit** | **0.715** | ~0 ms |
| Bi-Encoder (e5-base) | 0.560 | vorberechenbar |
| Cross-Encoder (bge-reranker) | 0.460 | ~150 ms/Stelle |

Der Cross-Encoder liegt auf **Zufallsniveau**, der Bi-Encoder knapp darüber.
Der einfache Keyword-Matcher gewinnt — jetzt **belegt** statt vermutet.

Die lehrreichste Erkenntnis war ein Fehlertyp, der dreimal auftrat: *Annahmen
über Randbedingungen nicht geprüft* (E5-Limit 512 Token, Cross-Encoder-Limit
für Anfrage+Dokument gemeinsam, eine Report-Datei die nie geschrieben wurde).
Und: Eine auf 4 Beispielen optimierte Konfiguration war auf 20 echten Labels
schlechter — **Overfitting an einer Mini-Stichprobe**.

Nächster sinnvoller Schritt ist daher nicht „noch ein Modell", sondern
**mehr Labels** zum Kalibrieren der bestehenden Lösung.

Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

### Backup

```bash
scripts/backup_chat.sh    # Chat-Verlauf + Checkpoints → auch als Markdown
scripts/backup_state.sh   # state.json/jobs.json (mit Integritätsprüfung)
```

> ⚠️ Der Chat-Verlauf liegt unter `~/.copilot/session-state/…` und wird vom
> Google-Drive-Sync **nicht** erfasst — dafür gibt es `backup_chat.sh`.

### Wichtig: Repo nicht auf dem Sync-Mount betreiben

Dieses Repository gehört auf ein **lokales** Laufwerk (z. B. `~/git/`), nicht
in den rclone-synchronisierten Google-Drive-Ordner. `bisync` kann Dateien
mitten im Schreiben zurücksetzen und so `.git` korrumpieren.

### Dokumentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Aufbau, Module, Datenfluss
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — Entscheidungen (ADRs)
- [`docs/CHAT-MEMORY.md`](docs/CHAT-MEMORY.md) — kuratiertes Projektwissen
- [`docs/BACKUP.md`](docs/BACKUP.md) — Backup, Restore-Tests, Automatisierung
