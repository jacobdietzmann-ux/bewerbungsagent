# Entscheidungen (ADR-Kurzprotokoll)

Architecture Decision Records im Kurzformat: *Kontext → Entscheidung → Grund*.
Diese Datei ist das „Langzeitgedächtnis" des Projekts.

---

## ADR-001 — Deterministisches Scoring statt LLM-Bewertung

**Kontext:** Der Fit-Wert entscheidet, ob Unterlagen erzeugt werden.
**Entscheidung:** Regelbasierte Keyword-/Inhaltswort-Überschneidung
(`matching.py`), kein LLM im Scoring.
**Grund:** Nachvollziehbar, reproduzierbar, unit-testbar, kostenlos.
Ein LLM-Score wäre nicht deterministisch und schwer zu prüfen.

---

## ADR-002 — History-Schutz für versendete Bewerbungen

**Kontext:** Massenlöschungen von Stellen mit niedrigem Fit.
**Entscheidung:** Status `sent`/`followup`/`interview`/`rejected` werden nie
gelöscht oder neu gescored.
**Grund:** Die Bewerbungshistorie ist ein Nachweis; ein späteres
Re-Scoring darf sie nicht rückwirkend „verschwinden" lassen.

---

## ADR-003 — Repo liegt NICHT auf dem Google-Drive-Mount

**Kontext:** Der Projektordner wird per rclone-`bisync` (alle 15 min)
mit Google Drive synchronisiert.
**Entscheidung:** Git-Repository unter `~/git/bewerbungsagent` (lokale Platte).
**Grund:** `bisync` kann lokale Änderungen zurücksetzen; Schreibvorgänge
mitten im Sync korrumpieren `.git`. FUSE ist zudem langsam.

---

## ADR-004 — Anonymisierte Fixtures für Tests

**Kontext:** Tests brauchen ein Profil, das echte Profil enthält PII.
**Entscheidung:** `tests/fixtures/profil-demo.json` mit fiktiven Daten;
`.gitignore` schließt `Profil-Datenbank.json` aus.
**Grund:** Keine echten Adressen/Telefonnummern in Repo oder CI-Logs.

---

## ADR-005 — Dashboard-Cache im Server invalidiert auch bei Template-Änderung

**Kontext:** `server.py` cached das gerenderte HTML und baute nur bei
Änderung von `state.json` neu. Änderungen an `dashboard.py` wurden ignoriert.
**Entscheidung:** Watcher vergleicht Änderungszeit von `state.json` **und**
`bewerbungsagent/dashboard.py`; beim Neubau wird das Modul per
`importlib.reload` frisch geladen.
**Grund:** Sonst zeigt das Live-Dashboard alte Templates, bis der Server
manuell neu gestartet wird.

---

## ADR-006 — „Gefunden am" nutzt `created`, nicht „heute"

**Kontext:** Die Wochenstatistik war falsch (alles in der aktuellen Woche).
**Entscheidung:** Datumspriorität `datum` → `created` → `sentAt` → heute.
**Grund:** `created` ist der echte Erfassungszeitpunkt; ohne ihn fielen alle
neu gefundenen Stellen auf „heute".

---

## ADR-007 — Klammerzusätze in Skill-Strings werden gesplittet (nach dem Strippen)

**Kontext:** `"ISO 26262 (funktionale Sicherheit)"` wurde verstümmelt.
**Entscheidung:** Erst Split-Regex, **dann** `strip("()")` auf die Teile.
**Grund:** Ein vorheriges `strip("()")` entfernt die schließende Klammer →
Split-Regex greift nicht mehr → `iso 26262` ist nie matchbar.

---

## ADR-008 — Zweisprachige Dokumente mit translations-Mapping

**Kontext:** In englischen PDFs blieben deutsche Skill-Labels.
**Entscheidung:** Explizite `*_TRANSLATIONS_EN`-Mappings in `documents.py`,
angewendet nur bei `lang == "en"`.
**Grund:** Sauber trennbar, testbar, und die deutschen Dokumente bleiben
unverändert. Jobtitel bleiben in Originalsprache (System-Abgleich).

---

## ADR-009 — Offline-Evaluation vor jeder „Verbesserung"

**Kontext:** Der Wunsch, das Matching durch KI-Methoden (Embeddings, LLM)
zu verbessern, ist ohne Messinstrument nicht überprüfbar.
**Entscheidung:** `eval/` mit Konfusionsmatrix, Precision/Recall/F1,
Threshold-Sweep und Majority-Baseline; Labels aus `state.json`.
**Grund:** Ohne Baseline ist jede „Verbesserung" eine Behauptung. Die
Evaluation zeigt zudem, dass **Accuracy** bei 83 % Negativ-Anteil irreführend
ist (Baseline erreicht 83 % Accuracy bei Recall 0).

**Status:** ⚠️ Erste Messung **zurückgezogen** — Labels waren falsch
(siehe ADR-012). Das Harness selbst bleibt gültig und wird weiterverwendet.

---

## ADR-010 — ⚠️ ZURÜCKGENOMMEN: `rejected` ≠ Nutzerentscheidung

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

## ADR-011 — Automatisch gelöschte Einträge sind keine Labels

**Kontext:** Die Pipeline löscht Stellen mit „Fit unter 60 %" automatisch.
**Entscheidung:** Solche Einträge werden aus dem Label-Set ausgeschlossen
(`include_auto_deleted=False`).
**Grund:** Es sind **Modell-Entscheidungen, keine Nutzerentscheidungen** —
sie als Ground Truth zu verwenden würde das Modell gegen sich selbst messen.

---

## ADR-012 — Status ist Prozess-, kein Eignungssignal

**Kontext:** Die erste Evaluation (ADR-009) leitete Labels aus dem
Feld `status` ab und kam auf F1 ≈ 41 %.
**Entscheidung:** Der Status beschreibt **ausschließlich den Bewerbungsprozess**
(`research` → `docs` → `sent` → `interview` → Absage/Abgelaufen). Er ist
**kein** Maß für Eignung und darf nicht als Fit-Label dienen.

**Begründung (vom Nutzer):**
> „Der Status der Stellen hat keinen Zusammenhang mit meiner Eignung zu der
> Stelle. Das ist nur der Status während des Bewerbungsprozesses."

**Konsequenz für die Evaluation:**
- `sent`/`followup`/`interview`/`rejected` = **alle** „beworben" → als
  Eignungslabel ungeeignet.
- Score-basierte Löschungen („Fit ≤ 60 %") sind **zirkulär** (Modell gegen
  sich selbst) → ungeeignet.
- Übrig bleiben nur **explizite Eignungsurteile**:
  - `deleted_reason == "Nicht passende Rolle (kein technisches Profil)"` (212)
    → grobe, aber echte Negative.
  - Notizen mit explizitem „Fit NN%"-Urteil (15) → zu wenige Positive.

**Fazit:** Der Bestand enthält **keine belastbare Ground Truth für Eignung**.
Eine seriöse Evaluation erfordert **manuell gesetzte Labels**
(→ `eval/label_tool.py`, Inter-rater/Annotation-Übung).

**Lehre:** Label-Semantik ist Teil der Modellspezifikation. Ein falsch
definiertes Label macht jede noch so saubere Metrik bedeutungslos — und
erzeugt plausibel aussehende, aber irreführende Zahlen.

---

## ADR-013 — Der Keyword-Fit trennt Eignung nicht (bisheriges Ergebnis)

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

## ADR-014 — Erste belastbare Baseline (20 manuelle Labels)

**Kontext:** Nach gezieltem Active-Learning-Labeling (Verdachtsstellen +
Kontrollen) liegen 20 manuelle Eignungs-Labels vor (10 passend / 10 nicht).

**Ergebnis:**

| Klasse | Scores | Mittel |
|---|---|---|
| passt | 26, 45, 49, 54, 58, 77, 81, 89, 90, 93 % | **66 %** |
| passt nicht | 26, 26, 26, 35, 43, 69, 69, 70, 71, 75 % | **51 %** |

- Trennkraft: **15 Punkte** (deutlich besser als die 8-Label-Messung mit -8).
- F1-Optimum bei Schwelle **45 %**: Precision 50 %, Recall 90 %, F1 64 %.
- Bei betrieblicher Schwelle **60 %**: Precision 50 %, Recall 50 %, F1 50 %.

**Interpretation:**
1. Der Keyword-Score ist **besser als zunächst gemessen**, aber weit von
   belastbar entfernt. Die frühere „Blindheit" war ein Artefakt der kleinen
   Stichprobe (viele Grenzfälle bei 26 %).
2. **Precision 50 % bei Schwelle 60 %:** Jede zweite Empfehlung ist falsch.
3. **Recall 50 %:** Jede zweite passende Stelle wird verpasst.
4. F1 64 % (bei 45 %) ist die **Messlatte für Embeddings**.

**Offen:** Weitere Labels nötig (Ziel 50/Klasse) für stabile Aussagen. Die
Stichprobe ist bewusst auf Grenzfälle fokussiert (Active Learning) und
deshalb *nicht* repräsentativ für den Gesamtbestand — der wahre Recall auf
allen 836 Stellen ist höher.

---

## ADR-015 — Semantisches Matching schlägt Keyword-Fit NICHT (Hypothese widerlegt)

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

## ADR-017: JobSpy als vierter Such-Provider (LinkedIn/Indeed/Google)

**Datum:** 2026-10-12
**Status:** akzeptiert

**Kontext:** Die Suche nutzte bisher DuckDuckGo/Bing (generische Web-Suche),
StepStone (direkt geparst) und manuellen Import. LinkedIn/Indeed/Glassdoor
standen auf der `_NON_JOB_HOSTS`-Blacklist, weil die Web-Suche auf diesen
Portalen nur Listing-/Redirect-Seiten liefert. Dadurch fehlte der Zugang zu
den Stellen, die viele Firmen **ausschließlich** über ihr ATS
(Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Personio, …) oder über
LinkedIn veröffentlichen.

**Entscheidung:** `python-jobspy` als vierten Provider integrieren
(`bewerbungsagent/search/jobspy.py`). Der Provider sucht über `linkedin`,
`indeed` und `google` (Google Jobs) und mappt die Ergebnisse in das interne
Format. Die vollständige Anzeigenbeschreibung wird als `beschreibung`
übernommen, sodass der langsame Browser-Fetch (`fetch_descriptions.py`) für
diese Stellen entfällt. `job_url_direct` wird vor `job_url` bevorzugt, weil er
häufig direkt auf das ATS zeigt.

**Wichtige Anpassungen:**
1. `_DIRECT_SOURCES` in `search/__init__.py`: Der Lexikon-/Aggregator-Filter
   (`_is_non_job_host`, `_is_listing_page`) gilt nur noch für rohe
   Web-Such-Treffer, nicht für strukturierte Quellen (StepStone/Import/
   LinkedIn/Indeed/Google Jobs) — sonst würden die LinkedIn-/Indeed-URLs
   sofort wieder herausgefiltert.
2. `jobspy_max_terms` (Standard 4): JobSpy ist langsam und liefert für
   verwandte Begriffe stark überlappende Treffer; daher läuft es nur auf dem
   ersten Teil der `query_terms`.
3. Lazy-Import von `jobspy` (pandas/pydantic) nur innerhalb von `search()`.

**Empirischer Befund (Live-Test am 2026-10-12):**
- **LinkedIn** liefert echte, deutsche Treffer (BWI GmbH, TGW Logistics,
  D.O.M., …) — funktioniert.
- **Indeed** antwortet mit HTTP 403 (Bot-Schutz; abhängig von IP-Reputation
  und Headern, ggf. über Proxies lösbar).
- **Google Jobs** (`udm=8`) liefert keine Daten — Googles Jobs-Vertikale ist
  upstream deprecated, der Scraper ist defekt.

**Konsequenz:** Der praktische Gewinn liegt aktuell bei **LinkedIn**. Indeed
und Google bleiben im `SITES`-Tupel (umgebungsabhängig, zukunftssicher), ihr
stilles Scheitern ist unkritisch (leere Ergebnisliste, keine Exception). Für
echte ATS-Abdeckung (Greenhouse/Lever/Ashby) ist ein separater Schritt nötig:
deren **öffentliche Job-Board-APIs** direkt abfragen (wie es
`NullSpace-BitCradle/jobhunter-framework` tut) — Google Jobs ist dafür kein
tragfähiger Weg mehr.

---

## ADR-018: SQLite + Alembic statt monolithischer state.json

**Datum:** 2026-10-12
**Status:** akzeptiert

**Kontext:** Der Bestand lag in einer einzigen ``data/state.json`` (~4 MB, 840
Einträge), die alle Felder pro Bewerbung vermischt — Provider-Daten (Suche/
Matching/Anreicherung/Dokumente) und Nutzer-Daten (Status, Notizen, Kontakt,
gelöscht, Interview-Datum). Am 12.10.2026 benannte der rclone-bisync die Datei in
``state.json.conflict1/2`` um (lokale UND Cloud-Seite gleichzeitig geändert),
wodurch das Dashboard kurzzeitig keine Quelle der Wahrheit mehr hatte.

**Entscheidung:** SQLite (``data/jobs.db``) wird die Single Source of Truth, mit
Alembic für Schema-Migrationen. Pro Bewerbung zwei JSON-Spalten:

- ``provider`` — alle Felder aus Suche/Fetch/Matching/Anreicherung/Dokumenten.
- ``user``    — alle Nutzer-Felder (Status, contact, notes, deleted, interviewDate,
  statusChangedAt, sentAt, deleted_reason, deletedAt).

Die Identität ist ``key`` (normalisierte URL bzw. Firma|Titel). Ein erneuter
Scrape überschreibt ausschließlich Provider-Felder; Nutzer-Felder werden von
``Store.apply_overlay`` (Dashboard) separat geschrieben und niemals angetastet
(Prinzip aus ``BjornMelin/ai-job-scraper``).

**Bisync-Interaktion (kritisch):** Eine SQLite-Datei darf **nicht** von bisync
synchronisiert werden (Binärdatei, nicht mergebar, WAL-Korruption). Deshalb:
1. ``jobs.db`` (+ ``-wal``/``-shm``) ist in ``bisync-exclude.txt`` ausgeschlossen.
2. ``state.json`` bleibt als **abgeleiteter Snapshot** bestehen (``Store.export_json``
   nach jedem Schreiben) und wird weiter über bisync → gdrive → HDD gesichert.
3. Bei DB-Verlust lässt sich der Bestand mit ``scripts/migrate_state_to_db.py``
   aus dem Snapshot wiederherstellen.

**Konsequenzen:**
- ``db.Store`` liefert dieselbe Dict-Struktur (``{"applications": [...], "updated": ...}``),
  sodass Pipeline, Server und Dashboard unverändert mit Dicts arbeiten.
- SQLAlchemy + Alembic sind neue Kern-Abhängigkeiten.
- Der Server überwacht für den Dashboard-Neubau jetzt die DB (inkl. ``-wal``),
  nicht mehr ``state.json``.

## ADR-021 – Relevanz-Triage vor dem Matching (regelbasiert)

**Kontext.** Die Suche lieferte auch domänenfremde Treffer (Taxifahrer, Vertrieb,
Marketing, Buchhaltung, Gastronomie). Sie landeten im Bestand, wurden gescort und
mussten nachträglich als „nicht passende Rolle" gelöscht werden — bei einem früheren
Lauf waren das 115 Einträge mit Studenten-/Praktikumsbezug.

**Entscheidung.** Ein eigenes Modul `bewerbungsagent/triage.py` klassifiziert jeden
Treffer anhand von **Titel und Firma** (ohne die Anzeige zu laden) in `relevant`,
`unsure` oder `reject`. Nur `reject` fliegt bereits in `run_search` heraus.

**Begründung.**

* Die Klassifikation braucht die Beschreibung nicht — die Anzeige wird erst geladen,
  wenn der Titel allein nicht reicht (spart Fetch-Zeit und Browsersitzungen).
* Drei Klassen statt zwei: „im Zweifel behalten" ist die richtige Voreinstellung.
  Ein False Negative (echte Ingenieursrolle verworfen) kostet eine Bewerbungschance
  und fällt nicht auf; ein False Positive kostet nur einen Eintrag, den der Fit
  ohnehin aussortiert.
* Eine Fremd-Domäne wird nur durch ein *fachliches* Technik-Signal entschärft, nicht
  durch ein Führungswort — sonst rutschte „Head of International Sales" durch.
* Verworfene Treffer werden in `data/triage_rejected.json` protokolliert, damit die
  Entscheidung nachvollziehbar bleibt und nichts stillschweigend verschwindet.
* Regelbasiert und deterministisch (kein Modell): gleiche Eingabe → gleiche Klasse.

**Parameter & Trade-offs.**

* Deutsche Komposita brauchen `\w*` statt `\b` vor dem Wortstamm
  („Industrie**mechaniker**", „Alten**pfleger**") — dieselbe Falle wie bei
  `has_role_signal`.
* `search.triage: false` schaltet die Triage ab.
* Bekannte Grenze: `unsure` ist bewusst großzügig (12 von 318 Stellen im Bestand).
  Erst ein Modell oder mehr Trainingsdaten können hier schärfer trennen.

**Status.** Umgesetzt. 67 Tests für den Klassifikator, 5 Integrationstests für die
Einbindung in die Suche.

## ADR-022 – Nutzerentscheidung für Triage-Restfälle

**Kontext.** Nach der Triage (ADR-021) blieben Fälle übrig, die ein Regelwerk nicht
prinzipiell entscheiden kann: „Sales Manager **Embedded** & Displays" nennt Technik,
meint aber Vertrieb; „(Senior) Consultant **Sicherheits**evaluierung" nennt Sicherheit
(vgl. SOTIF/Safety), ist aber Consulting in einem anderen Feld; „Projektleitung
**Versicherungs-Software**" nennt Software, ist aber Branchen-Projektleitung.

**Entscheidung.** Zwei Listen in der Konfiguration: `search.triage_reject` und
`search.triage_keep` (Titel-Fragmente, Teilstring-Vergleich, Groß-/Kleinschreibung
egal). Sie werden in `classify()` **vor** allen Regeln geprüft.

**Begründung.**

* Das ist strukturell dieselbe Situation wie bei `has_role_signal`: Ein Titel allein
  belegt keine Rolle. Nur liefert hier die Grammatik kein Signal — die Bedeutung hängt
  am Weltwissen (was ist „Finance Systems"?).
* Weitere Wörter in `_NON_TECH_SIGNAL` aufzunehmen wäre Overfitting: „Finance" kommt
  auch in „Finance Software Engineer" vor, und das *wäre* technisch. Aufzählung skaliert
  nicht — der Mensch entscheidet.
* `triage_keep` gewinnt gegen alles (inkl. Studenten- und Domänenregeln), damit eine zu
  breit geratene Reject-Regel nie eine echte Stelle entfernt. Die Fehlerarten sind
  asymmetrisch: ein verworfenes Ingenieursangebot fällt nicht auf.
* Die Entscheidung wird protokolliert („Nutzerentscheidung (verwerfen): …"), bleibt
  damit in `data/triage_rejected.json` und im Dashboard nachvollziehbar und ist
  reproduzierbar (Config = Quelle der Wahrheit).

**Parameter & Trade-offs.**

* Teilstring statt Regex: robuster gegen Tippfehler, lesbar für den Nutzer; eine
  bewusst breite Regel muss der Nutzer selbst verantworten.
* Die Listen gehören in die private `config.json` (persönliche Kriterien), nicht ins
  Repo; `config.example.json` zeigt sie leer.

**Status.** Umgesetzt. 9 Tests für den Mechanismus (Vorrang, Groß/Klein, leere Liste,
`keep` schlägt `reject` und Regeln, fehlende/kaputte Config-Werte).

## ADR-023 – Ablaufsteuerung als Graph (LangGraph), optional

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

## ADR-024 – Wöchentlicher Lauf per systemd-Timer (nicht Cloud)

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

* `scripts/wochenlauf.sh`: `agent.py ablauf --beschreibung alle --ohne-review`
  mit `flock` (kein Doppellauf), Log in `data/wochenlauf.log` (auf 2000 Zeilen
  begrenzt) und Statusdatei `data/wochenlauf-status.json`. Der Zustand
  `LAUFEND` ist während des Laufs sichtbar; `OK`/`FEHLER` danach.
* `bewerbungsagent-wochenlauf.timer`: `OnCalendar=Mon *-*-* 06:00:00`,
  `Persistent=true` (verpasster Lauf wird nachgeholt — kein Montag fällt aus),
  `RandomizedDelaySec=600`.
* `bewerbungsagent-wochenlauf.service`: `After/Wants=network-online.target`,
  `TimeoutStartSec=3600` (Browser-Fetches dauern).
* Fehler werden per `notify-send` gemeldet, **falls** eine Sitzung läuft; ein
  Hintergrunddienst hat oft kein Display, dann bleiben Log und Statusdatei.

**Neuer Schalter `--beschreibung`.** Der Graph lud bisher nur `unsure`-Fälle
nach (sparsam, für den Zwischenlauf). Für den Wochenlauf ist `alle` nötig: nur
mit vollständigem Anzeigentext ist der Fit präzise (Text-Treffer zählen 4 Punkte,
Titel-Treffer 6). Im Bestand fehlten 100 von 137 Texten (StepStone 69,
LinkedIn 31) — ohne `alle` würde der Wochenlauf den Fit für die Mehrheit der
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
Wochenlauf um 06:00.

**Status.** Umgesetzt und einmal vollständig durchgelaufen. Timer aktiv
(`systemctl --user list-timers`). Nächster automatischer Lauf: Montag 06:00.
Testabdeckung: 5 Tests für den Umfang-Schalter, 22 für den Graphen gesamt.
