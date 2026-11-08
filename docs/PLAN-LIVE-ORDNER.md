# Vorschlag: Live-Ordner hält nur noch Daten

**Status: Variante A entschieden (ADR-057), Code-Teil umgesetzt, Umzug offen.**
Entschieden wurde am 08.11.2026: Variante A, `glassdoor.py` kommt ins Repo, Linux und
der Raspberry Pi laufen weiter und ziehen mit um. Die Code-Änderungen aus dem
Abschnitt unten sind eingespielt und ändern ohne `BEWERBUNGSAGENT_HOME` nichts. Den
Umzug selbst führt niemand ohne ausdrückliches Go aus.

## Empfehlung

`04_Agent` bleibt, wo er ist, und behält seinen Namen, wird aber zum reinen
Datenordner. Der Code kommt aus einem eigenen Release-Checkout des Repos und wird
in das bestehende venv installiert. Eine Umgebungsvariable sagt dem Code, wo die
Daten liegen.

| | A: Datenordner + Release-Checkout (empfohlen) | B: Datenordner + Entwicklungs-Checkout | C: Zwei Orte bleiben, Abgleich per Skript |
|---|---|---|---|
| Code-Orte | einer | einer | zwei |
| Was läuft um 07:00 | ein bewusst freigegebener Stand | was gerade im Checkout liegt, auch halbfertige Arbeit | was zuletzt kopiert wurde |
| Rückweg | vorherigen Commit auschecken | Stand muss erst wiederhergestellt werden | Backup zurückkopieren |
| Aufwand | Code-Änderungen unten, Umzug | wie A, ohne zweiten Checkout | Skript und Abweichungstest |
| Drive-Sync kann Code zurückdrehen | nein | nein | ja (AGENTS.md, Regel 5) |

B scheidet aus, weil im Entwicklungs-Checkout regelmäßig uncommittete Arbeit liegt
(am 07.11.2026 33 Dateien). C löst das Problem nicht: `fetch_descriptions.py` hatte
genau so einen Fix nur im Live-Ordner.

## Ist-Zustand

- **Code-Ort ist Daten-Ort.** `AGENT_ROOT` ist der Ordner über dem Paket. Alles
  Relative hängt daran: `config.json`, `data/`, das Dashboard.
- **Relative Pfade stehen in den Daten.** Die `config.json` nennt
  `../02_Profil-und-Assets/…`, `../01_Bewerbungen`, `../00_Dashboard/dashboard.html`.
  Im Bestand stehen 1.560 Dokumentpfade, alle als `../01_Bewerbungen/…` relativ zu
  `AGENT_ROOT`. Foto und Unterschrift im Profil sind ebenso relativ angegeben.
- **Der Server rechnet vom Skriptordner aus.** `server.py` setzt
  `ROOT = <Skriptordner>/..` und sperrt `04_agent/config` und `04_agent/data/` per
  fest verdrahtetem Präfix.
- **Drei Starter kennen den Pfad.** Die Hermes-Wrapper `bewerbung_jobwatch.py`
  (07:00) und `bewerbung_mailcheck.py` (07:40) setzen `PROJECT`, `PYTHONPATH` und
  `cwd`; `dashboard-oeffnen.ps1` startet `server.py` aus `04_Agent`. Unter Linux
  kommen die systemd-Units aus `docs/systemd/` dazu, zuletzt gelaufen am 17.10.2026.
- **Im venv ist das Paket nicht installiert.** Importe laufen über `PYTHONPATH`
  oder den Skriptordner. Eine editierbare Installation findet nur die Pakete, nicht
  `agent.py`, `server.py` und `fetch_descriptions.py` (geprüft am System-Python).
- **Nur im Live-Ordner:** `bewerbungsagent/search/glassdoor.py` (nirgends importiert,
  die Provider-Tabelle kennt es nicht), abweichend `scripts/build_agent_map.py` und
  `eval/run_dimensions_eval.py`. Persönlich und nicht versioniert: `eval/labels.csv`
  und `eval/*report.md`.

## Zielbild

Der Kern: `AGENT_ROOT` bedeutet künftig **Datenordner**. Weil `04_Agent` Name und
Ort behält, bleiben alle relativen Pfade gültig. Die `config.json` und die
1.560 Dokumentpfade müssen nicht angefasst werden, das Dashboard rechnet weiter
von `2026/` aus.

| Liegt in `04_Agent` | Liegt im Release-Checkout |
|---|---|
| `config.json`, `data/`, `output/` | `bewerbungsagent/`, `migrations/`, `alembic.ini` |
| `eval/labels.csv`, `eval/*report.md` | `agent.py`, `server.py`, `fetch_descriptions.py` |
| ältere `config.json.*`, `backup-*` | `scripts/`, `eval/*.py`, `tests/`, `docs/` |

Die Datenbank bleibt in `%LOCALAPPDATA%\bewerbungsagent\jobs.db`
(`BEWERBUNGSAGENT_DB`). Die Code-Kopien wandern nach `05_Backups/`, sie werden
nicht gelöscht.

## Code-Änderungen vor dem Umzug (umgesetzt)

Ohne gesetzte Variable verhält sich alles wie heute. Die Änderungen lassen sich also
einspielen, ohne dass schon etwas umzieht.

| Stelle | Änderung |
|---|---|
| `bewerbungsagent/config.py` | `AGENT_ROOT` kommt aus `BEWERBUNGSAGENT_HOME`, sonst wie bisher. `dashboard.py`, `documents.py`, `followup.py` und `quality.py` folgen dadurch von selbst. |
| `server.py` | `ROOT`, `STATE_FILE` und der DB-Rückfall hängen an `AGENT_ROOT` statt am Skriptordner, `DASHBOARD_SRC` bleibt am Code. `_BLOCKED_PREFIXES` kommt aus `AGENT_ROOT.name`, damit die Sperre nicht am Ordnernamen hängt. |
| `scripts/jobwatch.py` | `AGENT_DIR` teilt sich in Code (`agent.py`, `cwd`) und Daten (`config.json`, `data/`). |
| `scripts/lauf.sh` | `AGENT_DIR` ist der Datenordner. Liegt dort noch `agent.py`, läuft wie bisher diese Kopie; sonst der Code aus dem eigenen Checkout mit `BEWERBUNGSAGENT_HOME`. Der Wechsel geschieht also von selbst, wenn die Code-Kopie verschwindet. |
| `eval/*.py` | `data/state.json` und `labels.csv` über `AGENT_ROOT` statt über den Skriptordner. |
| `pyproject.toml` | `py-modules = ["agent", "fetch_descriptions", "server"]`. Installation **editierbar**, weil `db._ensure_schema` `alembic.ini` und `migrations/` neben dem Paket erwartet. |
| `tests/conftest.py` | `BEWERBUNGSAGENT_HOME` vor jedem Import entfernen, sonst läse die Suite die echten Daten. |
| `search/glassdoor.py` | Aus dem Live-Ordner übernommen und als Provider `glassdoor` angebunden (nicht in der Standardliste; `glassdoor_radius`, `_min_salary`, `_max_salary` gehen an die Suche). |
| Tests | `tests/test_datenordner.py`, `tests/test_search_glassdoor.py`. |

Außerhalb des Repos sind danach drei Dateien anzupassen: die beiden Hermes-Wrapper
und `00_Dashboard/dashboard-oeffnen.ps1`.

## Ablauf des Umzugs (nur nach Freigabe)

1. Erledigt: `glassdoor.py` und `build_agent_map.py` sind im Repo;
   `eval/run_dimensions_eval.py` wich nur in der Importreihenfolge ab.
2. Code-Änderungen nach `main` bringen. Release-Checkout anlegen:
   `git worktree add ~/git/bewerbungsagent-live main`.
3. In das venv installieren: `pip install -e "<checkout>[graph,jobspy]"`.
4. Hermes-Jobs `jobwatch-bewerbung`, `jobwatch-mailcheck` und `bewerbung-autolabel`
   anhalten, den Dashboard-Server beenden.
5. `04_Agent` nach `05_Backups/` sichern, `jobs.db` mit `backup_state.sh` oder
   SQLite-Backup kopieren.
6. `BEWERBUNGSAGENT_HOME` setzen, die drei Starter umstellen.
7. Prüfen, solange die Code-Kopien noch liegen: `agent.py status`,
   `agent.py dashboard`, `jobwatch.py --no-search --dry-run`, `/healthz`, ein Dokument
   im Dashboard öffnen, „Ordner öffnen", `agent.py fetch --limit 1`.
8. Code-Kopien aus `04_Agent` entfernen und Schritt 7 wiederholen.
9. Hermes-Jobs wieder freigeben und den nächsten 07:00-Lauf im Protokoll prüfen.

**Linux (systemd):** Die Unit startet schon heute `~/git/bewerbungsagent/scripts/tageslauf.sh`
mit dem synchronisierten `04_Agent` als Argument. Vor Schritt 8 dort `git pull` und
`pip install -e` im venv `~/.venvs/bewerbungsagent`. Sobald bisync die Code-Kopien
entfernt, startet `lauf.sh` von selbst den Checkout. Danach `data/tageslauf.log`
prüfen: Die Startzeile nennt den Code-Ort.

**Raspberry Pi:** Von hier aus nicht einsehbar. Vor Schritt 8 klären, womit er
`agent.py` und `jobwatch.py` startet. Danach dort Checkout und venv anlegen und den
Starter auf `<checkout>/scripts/jobwatch.py` mit `BEWERBUNGSAGENT_HOME` umstellen.
Ohne diesen Schritt bricht der Pi ab, sobald die Code-Kopien weg sind.

**Rückweg:** Variable entfernen, Starter zurückstellen, Code-Kopien aus dem Backup
zurücklegen. Die Datenbank und die Daten ändern sich beim Umzug nicht.

**Ein Update danach:** `git -C ~/git/bewerbungsagent-live pull --ff-only`, Server
neu starten. Das Kopieren nach Regel 6 aus `AGENTS.md` entfällt, die Regel wird
gestrichen.

## Risiken

- **Variable fehlt in einem Starter:** Der Code läuft dann gegen den Checkout und
  findet keine `config.json`. Die Wrapper setzen die Variable deshalb selbst, statt
  sich auf die Nutzerumgebung zu verlassen; der Hermes-Gateway übernimmt neue
  Umgebungsvariablen erst nach einem Neustart.
- **Laufender Server mit altem Code:** Er bleibt bis zum Neustart im Speicher. Darum
  Schritt 4.
- **Weitere Rechner:** Linux und der Raspberry Pi sind in Betrieb und laufen aus dem
  synchronisierten Ordner. Ihr Starter muss vor Schritt 8 umgestellt sein, siehe oben.
- **Drive-Sync:** Beim Entfernen der Code-Kopien einen Sync-Lauf abwarten und prüfen,
  dass sie nicht wiederkommen.

## Entschieden (08.11.2026)

1. Variante A.
2. `glassdoor.py` kommt ins Repo und ist als Provider angebunden.
3. Linux und der Raspberry Pi laufen weiter und ziehen mit um.
