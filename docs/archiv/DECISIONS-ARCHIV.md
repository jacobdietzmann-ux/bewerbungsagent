# Archivierte Entscheidungen

Diese ADRs gelten nicht mehr. Sie bleiben als Begründung früherer Stände erhalten.

## ADR-010 — ⚠️ ZURÜCKGENOMMEN: `rejected` ≠ Nutzerentscheidung

> **Archiviert:** zurückgenommen (ADR-012).

**Ursprüngliche (falsche) Entscheidung:** `rejected` galt als negativ
(„nicht verfolgt").

**Warum sie widerlegt wurde:** `rejected` = „Abgelehnt/Abgelaufen" bedeutet,
dass die **Bewerbung versendet und von der Firma abgelehnt** wurde. Belege:
- 65 `rejected`-Einträge haben ein `sentAt` (Versanddatum).
- Notizen: „Absagegrund: spezifische Sprachkenntnisse gefordert",
  „CV an Hiring Manager weitergeleitet, spaeter dennoch Absage".
- Eine Absage ist eine Entscheidung der **Firma** und sagt nichts über die
  Eignung des Bewerbers.

**Siehe ADR-012** für die korrigierte Auffassung.

---

## ADR-013 — Der Keyword-Fit trennt Eignung nicht (bisheriges Ergebnis)

> **Archiviert:** überholt durch ADR-014.

**Kontext:** Erste manuelle Labels (8 Stück) wurden gesetzt, um den
Keyword-Fit gegen echte Eignungsurteile zu prüfen.
**Ergebnis:** Der Score trennt die Klassen **nicht** — im Mittel scoren
*unpassende* Stellen sogar höher:

| Klasse | Scores (manuell) | Mittel |
|---|---|---|
| passt | 26, 45, 49, 54 % | 44 % |
| passt nicht | 26, 26, 71, 75 % | 50 % |

Bei der betrieblichen Schwelle 60 %: **0 Treffer, 2 Fehlalarme, 4 verpasste
passende Stellen.** Das beste F1 liegt bei Schwelle 45 % mit 46 %.

**Ursache (Hypothese):** Keyword-Überlappung misst *Vokabular*, nicht
*Relevanz*. Anzeigen mit viel Text und generischen Begriffen
(„Systems", „Data", „Analytics" in „Head of Finance Systems") sammeln
Treffer, obwohl die Rolle nicht passt. Kurze, präzise Anzeigen passender
Stellen („Testmanager elektrische Antriebe" → 26 %) verlieren dagegen.

**Konsequenz:**
- Die Schwelle 60 % ist als Auswahlkriterium **nicht belegt**.
- Genau hier setzt Semantic Search (Embeddings) an — sie vergleicht
  *Bedeutung* statt Wörter.
- Die Stichprobe (8 Labels) ist klein; die Tendenz ist aber so deutlich,
  dass sie eine Neuausrichtung rechtfertigt.

**Werkzeug-Anpassung:** `run_eval` kennzeichnet Ergebnisse unter 30 Labels
als „VORLÄUFIG", zeigt aber die Trennkraft, statt zu schweigen.
`label_tool` unterstützt jetzt gezieltes Widerspruchs-Labeling (Active
Learning: die informativsten Labels sind die, bei denen der Nutzer vom Score
abweicht).

---

## ADR-015 — Semantisches Matching schlägt Keyword-Fit NICHT (Hypothese widerlegt)

> **Archiviert:** Experiment widerlegt, Code am 09.11.2026 entfernt (ADR-058).

**Hypothese:** Embeddings vergleichen *Bedeutung* statt Wörter und lösen daher
die Fälle, an denen Keyword-Überlappung scheitert (z. B. „Head of Finance
Systems, Data & Analytics" mit 75 % Keyword-Fit, obwohl es eine
Finance-Führungsrolle ist).

**Messung** (Modell `intfloat/multilingual-e5-base`, 20 manuelle Labels):

| Datensatz | Verfahren | AUC | P@5 |
|---|---|---:|---:|
| voll (230 Labels) | Keyword-Fit | **0.947** | **100 %** |
| voll (230 Labels) | Semantisch (kompakte Anfrage) | 0.924 | 40 % |
| voll (230 Labels) | Semantisch (voller Profil-Dump) | 0.776 | 40 % |
| **hart (20 Labels)** | **Keyword-Fit** | **0.715** | **100 %** |
| hart (20 Labels) | Semantisch (kompakte Anfrage) | 0.560 | 40 % |

**Ergebnis:** Hypothese **widerlegt**. Auf den harten Fällen (technische, aber
unpassende Stellen) liegt Semantik bei AUC 0.560 — praktisch Zufallsniveau
(0.5). Der Keyword-Fit ist deutlich besser.

**Warum es scheitert:**
1. **Ein einzelner Profil-Vektor verwischt die Trennschärfe.** Er wird zu einem
   generischen „technischen Ingenieur"-Vektor, der auf jede technische Stelle
   passt — Automotive-Test, SAP-Testmanagement, Embedded-Entwicklung.
2. **Das Ähnlichkeitsband ist zu schmal:** Kosinus 0.79–0.88 über 230 Stellen.
   Innerhalb dieses Bands ist die Rangfolge kaum aussagekräftig.
3. **Confound im Datensatz:** Die 212 groben Verwürfe sind *nicht-technische*
   Berufe (Finance, HR, Schweißlehrer). Beide Verfahren trennen die mühelos —
   das verdeckt die Schwäche bei *technischen* Fehlpaarungen.

**Der wertvollste Einzelbefund — ein Silent Bug:**
E5 schneidet bei 512 Token ab. Der ursprüngliche Profil-Text hatte ~1484
Token, es wurde also nur die erste Station eingebettet; der Rest verschwand
lautlos. Die kompakte Anfrage (`build_profile_query`) hob die AUC von 0.776 auf
0.924. **Eingabe-Aufbereitung wirkt stärker als Modellwahl.**

**Konsequenz:**
- `bewerbungsagent/semantic.py` bleibt als **experimentelles** Modul erhalten
  (dokumentierter Negativbefund), wird aber **nicht** in die Pipeline
  eingebunden.
- Opt-in-Installation über das Extra `[semantic]`; `torch` (CPU) wird nicht
  zur Standardabhängigkeit.
- Für echte Verbesserung wären **Cross-Encoder-Reranking** (gemeinsame
  Bewertung von Profil und Stelle) oder **Hybrid** (Keyword als Recall-Filter,
  Semantik als Reranker) nötig — nicht ein einzelner Profil-Vektor.

**Methodische Lehre:** Ein negatives Ergebnis ist ein Ergebnis. Es hat mehrere
Tage Fehlentwicklung erspart. Voraussetzung war, dass eine **Baseline mit
belastbaren Labels** existierte (ADR-014) — ohne sie wäre die Frage nicht
entscheidbar gewesen.

---

## ADR-016 — Cross-Encoder-Reranking hilft ebenfalls NICHT

> **Archiviert:** Experiment widerlegt, Code am 09.11.2026 entfernt (ADR-058).

**Hypothese:** Nach dem Scheitern des Bi-Encoders (ADR-015) sollte ein
**Cross-Encoder** besser sein: Er bewertet Profil und Stelle *gemeinsam*
(full attention) statt zwei getrennte Vektoren zu vergleichen. Damit sollten
die Details erhalten bleiben, die im Einzel-Vektor verloren gehen.

**Messung** (`BAAI/bge-reranker-base`, AUC / Precision@5):

| Verfahren | voll (230 Labels) | hart (20 Labels) |
|---|---:|---:|
| Keyword-Fit | **0.947** / 100 % | **0.715** / 100 % |
| Bi-Encoder (e5-base) | 0.924 / 40 % | 0.560 / 40 % |
| Cross-Encoder (natürliche Anfrage) | 0.539 / 40 % | 0.460 / 40 % |
| Cross-Encoder (Keyword-Anfrage) | 0.472 / 20 % | 0.320 / 20 % |

**Ergebnis: Hypothese erneut widerlegt.** Der Cross-Encoder liegt auf den
harten Fällen bei AUC **0.460 — schlechter als Zufall** (0.5). Er ist das
schlechteste aller getesteten Verfahren, bei ~150 ms pro Stelle.

**Nebenbefund:** Die natürliche Anfrageform schlägt die Keyword-Anfrage
konsistent (0.539 vs. 0.472; 0.460 vs. 0.320). Die Anfrage-Aufbereitung wirkt
also, reicht aber nicht.

**Der methodische Fehler (wichtigster Teil):**
Auf **4 handgeprüften Beispielen** sah die kurze natürliche Anfrage klar am
besten aus (AUC 0.730 vs. 0.600). Auf den 20 echten Labels kehrte sich das
Ergebnis um (0.460 statt 0.600). Ich hatte eine Konfiguration auf
Einzelfällen optimiert — **Overfitting an einer Mini-Stichprobe**. Ohne das
Label-Set wäre diese Fehlentscheidung unbemerkt geblieben und hätte zu einem
schlechteren System geführt.

**Weiterer Silent Bug (dritte Instanz derselben Familie):**
Der Cross-Encoder hat ein **gemeinsames** Token-Limit von 512 für Anfrage
UND Dokument. Die erste Anfrage hatte 295 Token, sodass der Stellenanzeige
nur 217 Token blieben — die Hälfte wurde stillschweigend abgeschnitten.
Das ist derselbe Fehlertyp wie in ADR-015 (E5-Limit) und beim
Report-Schreiben (`write_text` fehlte): **Annahmen über Randbedingungen
nicht verifiziert.**

**Konsequenz:**
- `bewerbungsagent/rerank.py` bleibt als dokumentierter Negativbefund,
  **nicht** in der Pipeline.
- Der **Keyword-Fit bleibt das beste Verfahren** für diesen Datensatz.
- Nächster sinnvoller Schritt ist nicht „noch ein Modell", sondern
  **mehr Labels** (50–100 je Klasse), um die bestehende Lösung zu kalibrieren.

**Gesamtbilanz der drei Experimente:** Die empirische Prüfung hat verhindert,
zwei komplexe, langsame und schlechtere Verfahren einzubauen. Der einfache
Keyword-Matcher gewinnt — aber jetzt ist das **belegt** statt vermutet.

---

## ADR-023 – Ablaufsteuerung als Graph (LangGraph), optional

> **Archiviert:** LangGraph-Ablauf am 11.11.2026 entfernt (ADR-059).

**Kontext.** `pipeline.run_full` ist ein Fließband: jeder Schritt läuft immer,
in derselben Reihenfolge, ohne Zurück. Das ist für deterministische Arbeit
richtig, hat aber drei Grenzen:

1. Die Relevanz-Triage (ADR-021) liefert `unsure`, wenn der Titel allein nicht
   reicht. Das Fließband kann darauf nicht reagieren — `fetch_descriptions`
   lädt entweder für alle Stellen die Beschreibung (teuer) oder für keine.
2. `fetch_descriptions` lädt Beschreibungen für *alle* Stellen ohne Text — auch
   für die, deren Titel schon eindeutig war.
3. Vor dem Versand gibt es keinen Haltepunkt im Ablauf.

**Entscheidung.** Ein Ablauf-Graph in `bewerbungsagent/orchestrator.py` mit
Zustand, Verzweigungen, zwei begrenzten Schleifen und einem Review-Knoten.
LangGraph kommt als **optionale** Abhängigkeitsgruppe `graph`.

**Begründung.**

* Der Graph ruft **dieselben** Funktionen auf (`run_search`, `run_match`, …).
  Er ändert die Logik nicht, nur die Reihenfolge und die Verzweigungen — dadurch
  bleiben 500+ Tests gültig.
* Optional, weil ein linearer Ablauf keinen Graphen braucht (Overhead). Der
  Nutzen entsteht erst durch Verzweigung/Schleife/Freigabe. Ohne Installation
  bleibt `agent.py pipeline` der Weg; `agent.py ablauf` meldet das klar.
* Eine Verzweigung mit **Obergrenze** (`MAX_BESCHREIBUNG_VERSUCHE`): Pflicht,
  sonst terminiert der Graph nicht.
* **Kein Graph-Retry für `generate`.** Erste Fassung hatte eine Schleife, die
  `generate` wiederholte, solange Dokumente entstanden — reine Doppelarbeit:
  `generate_anschreiben` kürzt intern (4 → 3 → 2 Aufzählungspunkte), ein
  erneuter Aufruf liefert dasselbe Ergebnis. Beim Live-Lauf kostete das drei
  vollständige Durchläufe à ~30 s. Entfernt; die Schleife, die wirklich etwas
  ändert, ist das Nachladen der Beschreibung.
* `fetch_descriptions(only_unsure=True)` ist neu: Lädt der Graph nur die
  unklaren Fälle nach, spart das die Browseraufrufe für alles andere.
* Der Review-Knoten ist ein **reiner Durchlauf**, kein Terminal-Dialog. Die
  Bewertung passiert dort, wo ohnehin gearbeitet wird: im Dashboard (Status
  ändern, Eintrag löschen). Doppelte Abfragen wären Reibung ohne Nutzen. Der
  Knoten bleibt, damit der Ablauf sichtbar macht, *dass* eine menschliche
  Entscheidung vor dem Versand steht — und ein späterer Modus „nur mit Freigabe"
  dort andocken kann. `--ohne-review` überspringt ihn.

**Nebenbefund (eigener Bug).** `run_generate` prüfte nicht, ob eine Stelle schon
Unterlagen hat: es liest `matches.json`, die Dokument-Info steht aber nur in der
DB. Jeder Lauf erzeugte dieselben 36 Stellen erneut. Behoben — der Mengenlauf
überspringt jetzt dokumentierte Stellen (im Live-Lauf 55), `--ids` erzeugt
weiterhin neu (ausdrücklicher Wunsch).

**Status.** Umgesetzt. 17 Tests (Graphstruktur, vollständiger Lauf, Schleife
terminiert, Review überspringbar, generate-Idempotenz).

## ADR-024 – Automatischer Lauf per systemd-Timer (nicht Cloud)

> **Archiviert:** systemd-Lauf auf dem Pi entfällt, Tageslauf läuft über Hermes (ADR-059).

**Kontext.** Der Ablauf soll automatisch laufen, damit die Stellen und Unterlagen
montags vorliegen. Die naheliegende Frage war, ob das ein Cloud-Deployment
braucht (Advisor-Punkt #5).

**Entscheidung.** Ein **systemd-User-Timer** auf dem lokalen Rechner, gebaut nach
demselben Muster wie `bewerbungsagent-backup.timer`. **Kein Cloud-Dienst.**

**Begründung.**

* **Datenlage.** Der Lauf braucht das Profil (Adresse, Telefon, Bewerbungen) und
  schreibt Bewerbungsunterlagen. Das gehört nicht zu einem Cloud-Anbieter, nur
  damit ein Timer feuert.
* **Technik.** Schritt 2 (`fetch`) braucht einen echten Chromium — lokal
  vorhanden und erprobt; in Lambda/Containern ist das zusätzlicher Aufwand ohne
  Gegenwert.
* **Verhältnismäßigkeit.** Zwei Unit-Dateien und ein Shell-Skript gegen
  Container, Secrets-Management, IaC und Monitoring. Das Muster existiert im
  Projekt bereits und ist damit wartbar.
* Cloud wäre erst sinnvoll bei **anderem** Bedarf: Rechner montags regelmäßig
  aus, oder Zugriff auf das Dashboard von unterwegs. Beides trifft nicht zu.
  Für das Berufsprofil bleibt #5 eine sinnvolle *Übung* — aber als bewusste
  Übung, nicht als Betriebsnotwendigkeit.

**Umsetzung.**

* `scripts/tageslauf.sh`: `agent.py ablauf --beschreibung alle --ohne-review`
  mit `flock` (kein Doppellauf), Log in `data/tageslauf.log` (auf 2000 Zeilen
  begrenzt) und Statusdatei `data/tageslauf-status.json`. Der Zustand
  `LAUFEND` ist während des Laufs sichtbar; `OK`/`FEHLER` danach.
* `bewerbungsagent-tageslauf.timer`: `OnCalendar=*-*-* 12:00:00`,
  `Persistent=true` (verpasster Lauf wird nachgeholt — kein Tag fällt aus),
  `RandomizedDelaySec=300`.
* `bewerbungsagent-tageslauf.service`: `After/Wants=network-online.target`,
  `TimeoutStartSec=3600` (Browser-Fetches dauern).
* Fehler werden per `notify-send` gemeldet, **falls** eine Sitzung läuft; ein
  Hintergrunddienst hat oft kein Display, dann bleiben Log und Statusdatei.

**Neuer Schalter `--beschreibung`.** Der Graph lud bisher nur `unsure`-Fälle
nach (sparsam, für den Zwischenlauf). Für den Tageslauf ist `alle` nötig: nur
mit vollständigem Anzeigentext ist der Fit präzise (Text-Treffer zählen 4 Punkte,
Titel-Treffer 6). Im Bestand fehlten 100 von 137 Texten (StepStone 69,
LinkedIn 31) — ohne `alle` würde der Tageslauf den Fit für die Mehrheit der
Stellen weiterhin nur aus dem Titel schätzen.

**Nebenbefund.** `data/triage_rejected.json` (ADR-021) fehlte in der
rclone-Ausschlussliste. Die Datei wird bei jedem Suchlauf neu geschrieben und
wäre damit ein Sync-Konfliktkandidat — wie `jobs.json`/`matches.json`. Ergänzt.

**Nebenbefund 2 (Log-Diagnose).** Python puffert stdout, wenn es nicht am
Terminal läuft — der Lauf arbeitete bereits mit Chromium, das Log zeigte aber
10 Minuten lang keine neue Zeile. Für einen Hintergrundlauf ist das fatal: der
einzige Hinweis, dass gearbeitet wird, fehlt. Behoben mit ``-u`` und
``PYTHONUNBUFFERED=1``.

**Erster echter Lauf (gemessen).** 561 s (9,4 min). 130 Stellen gefunden,
18 durch Triage verworfen, **130 Anzeigentexte nachgeladen** (vorher hatten nur
37 von 137 einen Text), 10 Unterlagen erzeugt, Dashboard 107 relevant. Die
9 Minuten sind der Preis für vollständige Texte — akzeptabel für einen
Hintergrundlauf.

**Rhythmus: wöchentlich → täglich.** Ursprünglich Montag 06:00. Der Rechner
läuft mittags ohnehin, und ein Tagesrhythmus hält die Liste aktuell, ohne dass
9 Minuten Rechenzeit ins Gewicht fallen. Deshalb `*-*-* 12:00:00` und der
ehrliche Name `tageslauf` statt `wochenlauf` — ein „Wochenlauf", der täglich
feuert, wäre eine Falle für den nächsten Blick in `systemctl --user list-timers`.

**Status.** Umgesetzt und einmal vollständig durchgelaufen. Timer aktiv
(`systemctl --user list-timers`). Testabdeckung: 5 Tests für den Umfang-Schalter,
22 für den Graphen gesamt.

## ADR-027 – Fit-Bänder: 50–64 % bleibt Research, erst ab 65 % entstehen Unterlagen

> **Archiviert:** Fit-Bänder ersetzt durch ADR-036 und ADR-059.

**Problem.** Die Unterlagen-Schwelle lag bei 50 % (`min_fit_for_generation: "mittel"`).
Damit bekamen Stellen im Band 50–64 % denselben Status `Dokumente erstellt` wie ein
80-%-Treffer. Der Nutzer sah im Dashboard 10 Bewerbungen, die er so nie verschickt
hätte — ein Anschreiben für einen 55-%-Treffer kostet Zeit und geht fast nie durch.

**Nebenbefund (der eigentliche Fallstrick).** `run_generate` las die Schwelle aus der
Konfiguration, `run_enrich` hatte sie mit `FIT_RANK["mittel"]` fest verdrahtet. Beide
standen zufällig auf 50, sodass es nicht auffiel — eine Änderung an
`min_fit_for_generation` wäre für die automatische Erzeugung aber wirkungslos
geblieben. Beide Wege nutzen jetzt `_fit_fuer_unterlagen(config)`.

**Entscheidung.** Die Grenzen stehen genau einmal, als benannte Konstanten:

| Fit | Status | Dokumente |
|---|---|---|
| < 50 % (`FIT_BAND_AUSBLENDEN`) | ausgeblendet | – |
| 50–64 % | `research` | keine |
| ≥ 65 % (`FIT_BAND_UNTERLAGEN`) | `docs` | ja |

* Konfiguration: `documents.min_fit_for_generation` = `hoch` (65 %, neuer Standard) |
  `mittel` (50 %) | `niedrig` (0 %). `FIT_RANK` übersetzt die Namen.
* **Rücknahme statt Löschen:** Bereits erzeugte Unterlagen im mittleren Band setzt
  `run_enrich` auf `research` zurück. Die Dokumente bleiben referenziert und auf der
  Platte; der Eintrag bleibt damit sichtbar und die Entscheidung umkehrbar. Nur der
  Status wird ehrlich — `docs` heißt „hier liegt eine Bewerbung".
* Versendete und abgeschlossene Bewerbungen (`sentAt`, `interviewDate`) werden nicht
  zurückgestuft: echte Aktivität wird nicht nachträglich kleingerechnet.
* Die Rücknahme orientiert sich am aktuellen Fit. Steigt ein Text nach dem Nachladen
  über 65 %, greift sie nicht mehr — der Lauf ist idempotent.

**Verworfene Alternative.** Unterlagen im mittleren Band löschen. Das vernichtet
bezahlte Rechenzeit und die Ordner sind der einzige Beleg, was der Agent gebaut hat.

**Testabdeckung.** `TestFitBaender` und `TestMengenlaufFitBand` in
`tests/test_enrich_cleanup.py` (12). Die Fixtures stehen auf dem neuen Standard
`hoch`, damit Tests und Auslieferung nicht auseinanderlaufen.

## ADR-031 – Mehrdimensionale Bewertung berichtend, K.O. nur als Gate

> **Archiviert:** Mehrdimensionale Bewertung am 11.11.2026 entfernt (ADR-059).

Der Review vom 25.10.2026 kritisiert zu Recht, dass ein Fit von 80 % eine
unpassende Stelle nicht ausschließt: Der Keyword-Fit misst Vokabular, nicht
Verantwortungsniveau, Gehalt oder Arbeitsmodell. Andererseits gilt ADR-014/016:
Ein neues Verfahren wird erst eingebaut, wenn es die Baseline (AUC 0,715) auf
den harten Labels schlägt. Beides zusammen ergibt zwei getrennte Stufen.

**Entscheidung.**

1. `dimensions.py` bewertet sieben Dimensionen (Kompetenz, Aufgaben,
   Seniorität, Technologie/Branche, Gehalt, Arbeitsmodell, Entwicklung) mit
   Belegen. Die Gewichte (30/20/15/10/10/10/5) sind Startwerte aus dem Review,
   ausdrücklich Hypothesen.
2. Die Dimensionen laufen **berichtend**: `score` bleibt der Keyword-Fit;
   `dimensionen` wird in `run_enrich` berechnet, in SQLite gespeichert und im
   Dashboard als „Dim NN %“ mit Tooltip angezeigt.
3. Hart ist nur die **K.O.-Liste** — ein Anzeigen-Gehalt, dessen oberes Ende
   unter `ko_gehalt_min_tsd` (Standard 55 T€) liegt, plus optional
   Titel-Muster (`ko_senioritaet`, Standard leer). K.O. blockiert nur die
   automatische Unterlagenerzeugung; die Stelle bleibt sichtbar und per
   `--ids` bedienbar. Eine falsch gesetzte Schwelle darf keine Stellen
   verschwinden lassen.
4. Schätzungen („Xing-Schätzung“) zählen nicht als Anzeigen-Gehalt — sonst
   entstünde eine K.O. aus einer fremden Schätzung.

**Begründung der Stufen.** Die K.O.-Logik ist unabhängig von der Gewichtung
validierbar („wäre diese Stelle trotz gutem Fit nie gewollt?“), die Gewichte
nicht. Deshalb zuerst das Gate, dann die Messung.

**Grenzen (Stand 25.10.2026).** `eval/labels.csv` enthält 20 manuelle Labels,
von denen 13 noch einen Bestandseintrag treffen; auf dieser Basis trennt der
Keyword-Fit (AUC 100 %) nicht schlechter als die Dimensionen (98,8 %). Das ist
kein Beleg für die Dimensionen — es ist ein zu kleiner Datensatz. Die
Dimensionen bleiben berichtend, bis ≥ 50 Labels je Klasse vorliegen.

**Testabdeckung.** `test_dimensions.py`: Gewichte/Normalisierung, sieben
Dimensionen mit Belegen, Senioritätsstufen, Gehalts-Parsing, K.O. (Gehalt,
Xing-Schätzung, konfigurierte Seniorität), Merge in den Bestand,
Dashboard-Zusammenfassung.

## ADR-036 – Research beginnt bei 65 %, Unterlagen unter der Schwelle werden verborgen

> **Archiviert:** Research-Filter ersetzt durch die drei Regeln aus ADR-059.

Ausgangslage: Im Dashboard standen immer wieder Stellen mit 60–64 % im Status
`Research` — zuletzt ein 62-%-Treffer mit alten Unterlagen. Ursache war das
Research-Fenster `fit_min = 60`: Der Filter hielt 60–70 %, und eine dokumentierte
Stelle blieb zusätzlich über die Regel „erzeugte Dokumente bleiben sichtbar“
im Bestand. Beides zusammen erzeugte sichtbare Research-Fälle unter 65 %.

**Entscheidung.**

1. `research_filter.fit_min` ist standardmäßig **65** (Fenster 65–70 %). Unter
   65 % ist ein Fund kein Research-Fall; die Unterlagen-Schwelle bleibt 71 %.
2. Wird der Status einer dokumentierten Stelle unter der Schwelle auf
   `research` zurückgenommen, wird sie **im selben Lauf** verborgen
   (`deleted`, Grund `research-kriterium: FIT … < 65 %`). Die Dateien bleiben
   liegen; es wird nichts gelöscht.
3. Die Regel „erzeugte Dokumente bleiben sichtbar“ gilt nur noch für
   ausdrücklich angeforderte Unterlagen (`unterlagen_gewuenscht`) und für
   echte Aktivität (`sentAt`/`interviewDate`). Das Flag ersetzt die pauschale
   Annahme, jede alte Datei sei eine bewusste Entscheidung.
4. Bestehende Research-Fälle unter 65 % wurden am 25.10.2026 einmalig
   bereinigt (62 Einträge, Grund `research-kriterium`).

**Warum 65 und nicht 60:** Die Unterlagen-Schwelle liegt bei 71 %. Ein Fund
mit 60–64 % ist acht bis elf Punkte davon entfernt; er bindet Aufmerksamkeit,
ohne eine Bewerbung zu tragen. 65 % ist der Punkt, ab dem die Lücke klein
genug für eine Einzelfallprüfung ist.

**Grenzen.** Die Pendelweg-Ausnahme (bis Grenze + 10 min) hält weiterhin auch
schwache Funde als Research — sie sind ohne Unterlagen und ohne
`research_sichtbar` unsichtbar. Die Grenze ist Konfiguration, keine Messung.

**Testabdeckung.** `test_research_filter.py`: Default 65, 62 % mit Unterlagen
wird entfernt, 65 % bleibt. `test_enrich_cleanup.py`: dokumentierte Stelle ohne
Auftrag wird nach Rücknahme verborgen, mit `unterlagen_gewuenscht` bleibt sie
`docs` und sichtbar.

## ADR-037 – Stellenbezogenes Lebenslauf-Tailoring als eigenes File

> **Archiviert:** Lebenslauf-Tailoring am 11.11.2026 entfernt (ADR-059).

Ausgangslage: Der Lebenslauf entstand aus der eigenen DOCX-Vorlage, wobei nur
der Profil-Absatz pro Stelle ersetzt wurde — Stationen, Bullets und
Fähigkeitsgruppen blieben für jede Bewerbung identisch. Für eine
Integrationsstelle mit Schwerpunkt Schnittstellen, Systemtests und Automation
stand damit dasselbe Dokument wie für eine HiL- oder ADAS-Stelle, obwohl 10
Jahre Material mit genau diesen Schwerpunkten vorhanden sind.

**Entscheidung.** Ein optionales File `Lebenslauf-Tailoring.json` im
Bewerbungsordner steuert den Lebenslauf:

1. `headline`, `profil`, `kernkompetenzen` — Fließtext und Karten, sprachabhängig.
2. `berufserfahrung[]` — pro **konsolidierter** Station (Index, siehe
   `documents._consolidate_experience`) Rollentitel und Bullets.
3. `skills.gruppen[]` / `skills.weitere` — Auswahl, Reihenfolge und Benennung
   der Fähigkeitsgruppen.

Liegt das File, wird der Lebenslauf mit ReportLab gebaut statt aus der
DOCX-Vorlage: die Vorlage erlaubt nur das Ersetzen eines Absatzes, ein
Tailoring stellt aber Bullets, Gruppen und Karten um. Ohne File bleibt alles
wie vorher.

**Grenze gegen Erfindungen.** `tailoring.unbacked_terms()` prüft jeden
Fachbegriff der Fähigkeitslisten gegen die Profil-Datenbank und meldet
Unbelegtes beim Erzeugen; Begriffe aus `gap_terms` (bestätigte Lücken) werden
als solche ausgewiesen. Das Tailoring darf auswählen, umformulieren und
weglassen — nicht hinzufügen. Konkret für die x1F-Stelle blieben REST/SOAP,
Kafka, Java, Spring Boot, Apache Camel, Guidewire, Docker, SQL,
UML/Sequenzdiagramme und Versicherungsumfeld außen vor, weil das Profil sie
nicht hergibt (Docker ist dort ausdrücklich als Lücke vermerkt).

**Nebenbefund, mitbehoben.** `check_application()` benutzte den Schlüssel
`anschreiben_de`/`anschreiben_en` direkt als Sprachkürzel. Der
Behauptungs-Abgleich suchte damit `bullets_anschreiben_en`, fand keine Belege
und meldete jede Aussage des Briefs als unbelegt — der Ordner galt fälschlich
als fehlerhaft. Die Sprache wird jetzt aus dem Schlüssel abgeleitet, und jeder
Brief-Befund trägt sie im Detail (`[EN] …`).

**Grenzen.** Indizes beziehen sich auf die konsolidierte Stationsliste; ändert
sich `work_experience`, muss das File nachgezogen werden (die Bullets werden
dann stillschweigend falsch zugeordnet). Die Seitenlänge ist nicht garantiert:
ein zu üppiges Tailoring erzeugt eine dritte Seite, was nur der Blick ins PDF
zeigt. Der Tailoring-Text selbst wird nicht gegen das Profil geprüft (nur die
Fähigkeitslisten) — Fließtext bleibt Autorenverantwortung.

**Testabdeckung.** `test_tailoring.py`: Datei lesen/fehlerhaft, Sprachwahl mit
Deutsch-Rückfall, Index-Überschreibungen, Gruppen-Reihenfolge, Karten,
Beleg-Prüfung inklusive bestätigter Lücke, Profilabsatz und PDF-Erzeugung.
`test_quality.py`: Sprachschlüssel, Sprach-Marker im Befund.

## ADR-055 – Stellen ohne Anzeigentext verschwinden nicht mehr still

> **Archiviert:** Prüffall „Text fehlt“ am 11.11.2026 entfernt (ADR-059).

**Problem.** Ohne Anzeigentext bewertet der Score nur den Titel. Ein Rollentreffer
erreicht so nie 50 %: Auf 341 Stellen mit Text und Rollensignal ergab der reine
Titel-Fit in allen Fällen weniger als 50 %. Mit Text kamen 24,6 % auf mindestens
65 % und 19,6 % auf mindestens 71 %. Ohne Rollensignal (n = 996) waren es 3,5 % und
1,7 %. Am 07.11.2026 lagen 53 ausgeblendete Rollentreffer ohne Text unter
„FIT < 50 %“: 27 Mail-Leads, 16 Arbeitnow, 8 StepStone, 2 LinkedIn. Gezählt wurde
nach `auswahl.stille_rollentreffer`: Software- und Entwicklerrollen sind
ausgenommen, mit ihnen sind es 56.

Es gab drei Ursachen:

1. `fetch` und `match` arbeiten nur auf `jobs.json`, also auf dem letzten Suchlauf.
   28 der 29 betroffenen Stellen mit URL standen dort nicht mehr. Beim Direktaufruf
   lieferten 21 noch Text, darunter eine Stelle mit 100 % Fit (Agile Robots).
   8 Anzeigen waren abgelaufen. ADR-053 hilft dem Altbestand nicht: Keine der
   18 Arbeitnow-Stellen steht auf API-Seite 1 (`arbeitnow_pages: 1`).
2. Mail-Leads haben keine URL, also kann `fetch` keinen Text laden.
3. Abgelaufene LinkedIn-Links leiten auf eine Trefferliste weiter
   (`trk=expired_jd_redirect`). Deren Text wäre als Anzeigentext gespeichert worden.

**Entscheidungen.**

1. **Textlücken aus dem Bestand** (`pipeline._textluecken`). Rollentreffer ohne Text,
   mit URL und jünger als 30 Tage (`TEXT_NACHLADEN_TAGE`) laufen im Tageslauf mit
   `fetch` und `match` mit, bis Text da ist oder die Anzeige als abgelaufen gilt.
   Nutzerlöschungen und abgeschlossene Vorgänge bleiben außen vor.
2. **URL-Suche für Mail-Leads** (`search.resolve_mail_leads`, `manual.lead_passt`).
   Der Lauf sucht Firma + Titel bei XING, alle Begriffe in einer Browsersitzung, jeden
   Lead höchstens einmal in 7 Tagen. Gemessen auf 27 Leads: XING fand 5, alle richtig.
   StepStone fand 0, obwohl die Firma in 12 Fällen erschien. LinkedIn antwortete mit
   429, Google lieferte nichts, Bing nur allgemeine Seiten, DuckDuckGo blieb leer.
   Indeed ist ausgeschlossen, weil die Suche dort nur mit abgeschalteter
   Automationserkennung klappt. Der Abgleich ist bewusst streng (Titel-Jaccard ≥ 0,8,
   gekürzte Mail-Titel über den Anfang). Die gefundene URL füllt den
   Bestandseintrag des Leads über `bestand_key` und legt keinen zweiten an.
   `search.lead_url_provider: []` schaltet die Suche ab.
3. **Prüffall „Text fehlt, Titel passt“** (`auswahl.text_fehlt_titel_passt`). Der
   Nutzer hat die Regel am 08.11.2026 mit 14 Tagen Frist freigegeben. Eine Stelle
   wird nicht wegen `FIT < 50 %` ausgeblendet, wenn alle Bedingungen gelten:
   - kein Anzeigentext,
   - Rollensignal im Titel,
   - keine Software-, Entwickler-, Studenten- oder Technikerrolle,
   - Anzeige nicht abgelaufen,
   - Pendelweg innerhalb der Grenze,
   - jünger als 14 Tage (`TEXT_FEHLT_TAGE`).

   Sie trägt dann `text_fehlt` und steht im Dashboard in einer eigenen Liste mit Link
   oder Websuche und „Verwerfen“. Sie steht nicht in der Tabelle und in keiner
   Kennzahl und bekommt keine Unterlagen. Score, Fit-Bänder und Research-Fenster
   bleiben unverändert. Kommt Text, entscheiden die normalen Bänder. Nach der Frist
   blendet der Lauf die Stelle mit dem Grund „Text fehlt seit über 14 Tagen“ aus.
4. **Ehrliche Gründe.** Eine abgelaufene Anzeige ohne Text heißt
   „Anzeige abgelaufen (ohne Text)“. Ein Mail-Lead, dessen Anzeige mit Text schon im
   Bestand liegt, wird „Dublette: dieselbe Stelle wie …“. Beide Gründe und
   „Text fehlt …“ bewertet der Lauf neu, sobald sich Fit oder Text ändern.

**Messung** auf einer frischen Kopie des Bestands (08.11.2026, 2.262 Einträge) mit
dem echten `run_enrich`. Pendelweg und Unterlagenerzeugung waren dabei abgeschaltet:

| Lauf | Stille Rollentreffer | Prüffälle | Geänderte Scores |
|---|---|---|---|
| vorher | 53 | – | – |
| nur Regel | 8 | 45 | 0 |
| Regel + gemessene Texte (29 Direktaufrufe, 7 XING-Leads) | 0 | 22 | – |

In der Zeile „nur Regel“ sind 4 der 8 Stellen wegen des Pendelwegs ausgeblendet
(Pendelweg 31 bzw. 72 min, harte Grenze). Ihr Grund lautet weiter „FIT < 50 %“.

Mit Text verteilen sich alle 56 Stellen (53 plus 3 Software-Rollen) so: 6 sichtbar
mit 70–100 %, 22 mit Text bewertet und begründet ausgeblendet, 7 abgelaufen,
1 Dublette, 19 Prüffälle, 1 wegen des Pendelwegs ausgeblendet. Fünf
Stellen erfüllen danach die Bedingungen für automatische Unterlagen: Agile Robots
100 %, Instaffo 92 %, Hays 78 %, Simovative 74 %, Bertrandt 72 %. Die vorher 0–14 %
dieser Mail-Leads waren reine Titel-Fits.

**Grenzen.**
- Die Leads einer Mail sind n = 27. Die XING-Quote (5 von 27) ist eine Tendenz, kein
  Dauerwert.
- XING ohne Ortsfilter fand 2 weitere Leads (Velden, Dresden), geprüft wurden aber
  nur 12 von 22. Die Suche läuft deshalb mit dem Ort aus `search.location`.
- Für die Messung der Mail-Leads stand ihr Fit aus dem Direktaufruf in der Kopie,
  nicht der volle Text.
- Nach dem Merge mit `claude/musing-wing-5e7366` prüft `_vom_nutzer_geloescht`
  `deleted_code == DELETE_NUTZER` statt des Textvergleichs.
