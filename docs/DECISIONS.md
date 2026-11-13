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

## ADR-025 – „Neu gefunden"-Label aus dem protokollierten jüngsten Fund

**Problem.** Nach einem Lauf soll auf einen Blick erkennbar sein, welche Stellen
er mitgebracht hat. Der Bestand wuchs auf 320 Einträge; ohne Markierung muss man
„Gefunden am" spaltenweise vergleichen.

**Entscheidung.**

* Gespeichert wird der ``created``-Stempel des **jüngsten Fundes**, nicht das
  Zeitfenster des letzten Laufs (`meta`-Schlüssel ``letzter_fund``). Grund: ein
  Lauf ohne neue Funde hätte das Label sonst bei allen Stellen gleichzeitig
  verschwinden lassen, obwohl die Funde die neuesten bleiben.
* ``created`` wird in `_merge_state` einmal je Lauf für alle neuen Stellen
  gesetzt und danach nie überschrieben (``setdefault``) — es ist damit ein
  verlässlicher „zuerst gesehen"-Zeitstempel.
* Vergleich über `datetime`, nicht über Zeichenketten. `2026-10-15T16:14:00+02:00`
  und `2026-10-15T16:14:00+00:00` sortieren als Text fast gleich, sind aber zwei
  Stunden auseinander. Nicht vergleichbare Werte (naiv vs. zeitzonenbewusst,
  fehlend, unparsbar) ergeben **kein** Label — lieber kein Label als ein falsches.
* Neu gefundene Stellen werden **sichtbar, auch ohne Unterlagen**. Die
  Standardregel („nur dokumentierte Stellen") gilt weiter, aber ein Fund hat per
  Definition noch keine Dokumente — ohne diese Ausnahme wäre das Label nie zu
  sehen. Es sind 4 der 8 Funde vom 15.10. sichtbar; die übrigen 4 liegen
  ausserhalb der Pendelgrenze und bleiben ausgeblendet. Der Hinweistext nennt
  deshalb beide Zahlen.
* `research` ist jetzt ein regulärer Einblend-Schalter. Die KPI-Karten und der
  Wochenverlauf nehmen Research-Einträge weiterhin aus; die Status-Verteilung
  folgt der Tabelle, damit Diagramm und Tabelle dieselben Zahlen zeigen.

**Verworfene Alternative.** „Zeitfenster des letzten Laufs" (`start <= created <=
ende`) ist einfacher, liefert aber nach einem Lauf ohne neue Funde ein leeres
Ergebnis und ist damit für die Frage „was ist neu?" unbrauchbar.

**Testabdeckung.** 22 Tests (`tests/test_dashboard_neu_label.py`): Grenzfälle des
Zeitvergleichs, Zeitzonen, fehlende/unparsbare Werte, Sichtbarkeit neuer Funde,
Anzeigetexte, Research-Schalter.

## ADR-026 – Was ein Lauf anfassen darf (Rollen-Schutz und Nutzerfelder)

Zwei Fehler mit derselben Wurzel: der Graph rief `run_generate` als Mengenlauf auf
und schrieb anschließend den gesamten Zustand zurück.

**Fehler 1: Rollen-Schutz fehlte im Mengenlauf.** `run_enrich` erzeugt Unterlagen
nur, wenn der Titel ein Test-/Absicherungs-Signal trägt (`has_role_signal`) — ein
hoher Fit entsteht sonst über generische Technologie-Treffer. `run_generate` hatte
diesen Filter **nicht**. Der Lauf erzeugte dadurch für 20 Software-/Hardware-Rollen
(Broadcast Engineer, Technischer Autor, HPC Systems Administrator, …) komplette
Unterlagen und setzte ihren Status von `neu` auf `docs`.

*Fix.* Der Mengenlauf (`job_ids is None`) prüft jetzt dasselbe Signal und meldet
die Übersprungenen als `skipped_role`. `--ids` bleibt ausdrücklich unberührt: eine
namentlich gewählte Stelle ist eine Entscheidung, kein Zufallstreffer.

**Fehler 2: Ein laufender Prozess überschrieb Nutzerfelder.** `save_state` ersetzt
den gesamten Zustand. Ein Lauf lädt den Zustand, arbeitet minutenlang und schreibt
am Ende zurück — Änderungen, die der Nutzer währenddessen im Dashboard macht
(z. B. „Versendet"), fielen dabei auf den Stand vom Beginn des Laufs zurück.

*Fix.* Beim Voll-Schreibvorgang gewinnt die Datenbank für Felder, die der Lauf
nicht besitzt (`sentAt`, `notes`, `contact`, `interviewDate`, `statusChangedAt`),
und ein als erledigt markierter Status (`sent`, `followup`, `interview`,
`rejected`) wird nicht auf `neu`/`docs` zurückgestuft. Das Dashboard schreibt
weiterhin über `apply_overlay` direkt in die Nutzerspalte und darf alles ändern.

**Reparatur.** Die 21 Statusänderungen des Fehllaufs wurden auf den Stand vom
15.10.2026 09:51 zurückgesetzt; die 20 dabei entstandenen Bewerbungsordner liegen
in `data/quarantaene/` (nichts gelöscht). Skript: `scripts/repair_fehllauf.py`.

**Testabdeckung.** `tests/test_db_user_protection.py` (13) und
`TestMengenlaufRoleGuard` in `tests/test_enrich_cleanup.py` (3).

## ADR-028 – Pendelweg: „nahe München" entfernen, Fehlschläge nicht zwischenspeichern

Zwei Fehler, die zusammen dazu führten, dass die harte 30-Minuten-Grenze
unbemerkt umgangen wurde.

**Fehler 1: Ortszusatz nur teilweise entfernt.** `_strip_noise` kannte
„Poing bei München", aber nicht „Kaufering nahe München". Der Zusatz blieb
stehen, Nominatim fand nichts, und die Stelle hatte danach **gar keinen
Pendelweg**. `exceeds_commute_limit` liefert für unbekannte Werte bewusst
`False` („eine fehlende Angabe ist kein Ausschlussgrund") — die Folge: eine
Hilti-Stelle in Kaufering (75,5 km) bekam bei 76 % Fit komplette Unterlagen.

*Fix.* Ein gemeinsames Muster entfernt den Regionszusatz nach `nahe`, `nähe`,
`bei`, `raum`, `umgebung`, `großraum` vor „München". Hilti wird jetzt mit
**53 min** geroutet und ausgeblendet.

**Fehler 2: Fehlschläge wurden dauerhaft gespeichert.** `geocode` schreibt bei
leerem Ergebnis `None` in den Cache und gab das beim nächsten Aufruf zurück,
ohne erneut zu fragen. Ein einmaliger Fehlschlag — etwa wegen eines störenden
Zusatzes — blieb damit **für immer** bestehen. 15 Orte standen so dauerhaft auf
„Nicht ermittelt", darunter Gilching, Poing, Gräfelfing und Erding, obwohl die
reine Stadtangabe problemlos auflösbar ist.

*Fix.* `save()` schreibt keine `None`-Einträge mehr. Innerhalb eines Laufs bleibt
der Fehlschlag im Speicher-Cache (kein zweiter Aufruf für denselben Ort), über
Läufe hinweg wird er erneut versucht. Der Altbestand wird beim nächsten
Speichern bereinigt. Kosten: ein Request je unauflösbarem Ort und Lauf,
gedrosselt auf 1,1 s.

**Offen bleibende Fälle.** 23 Einträge haben gar keinen Ort, einer „Bavaria,
Germany" (kein Arbeitsort). Dort bleibt der Pendelweg unbekannt und die
Grenze greift nicht — bewusst, weil eine fehlende Angabe nichts ausschließt.
Für die Dokumenterzeugung ist das ein Restrisiko; sichtbar ist es im Dashboard
als „k. A.".

**Testabdeckung.** `tests/test_commute_locations.py` (2) und
`tests/test_geocode_cache.py` (4).

## ADR-029 – Schlüssel: Unicode-Striche falten, Dubletten zusammenführen

**Problem.** Der Schlüssel einer Bewerbung ist `normalize(url)`. `normalize`
löste Umlaute auf, faltete aber keine Strichvarianten. StepStone liefert
dieselbe Anzeige (Job-ID 14315467) einmal mit `c-uas` (U+002D) und einmal mit
`c‐uas` (U+2010) — daraus wurden **zwei Schlüssel und zwei Einträge** für
dieselbe Stelle.

Die Folge war genau das Muster, das der Nutzer zuvor gemeldet hatte: Der erste
Eintrag war `sent` mit Unterlagen, der zweite `neu` ohne Unterlagen. Bei einer
erneuten Erzeugung hätte die längst versendete Bewerbung als frischer Fall
erschienen.

**Entscheidung.** `normalize` faltet U+2010, U+2011, U+2012, U+2013, U+2014,
U+2015, U+2212, U+FE63 und U+FF0D auf `-`; U+00AD (weiches Trennzeichen) wird
entfernt. Anders als zunächst geschrieben braucht `str.translate` ein
`str.maketrans`-Objekt mit Ordinalzahlen — ein Dict mit Zeichen als Schlüssel
wirkt stillschweigend gar nicht.

**Wirkung auf das Matching: null.** Auf dem Bestand (135 Anzeigen) ändert die
Faltung keinen einzigen Score — sie betrifft nur den Schlüssel, nicht die
Trefferbewertung.

**Bereinigung.** `scripts/dedupe_schluessel.py` findet Zeilen, deren Schlüssel
nicht mehr zur heutigen Regel passt, während der kanonische Schlüssel bereits
von einer anderen Zeile belegt ist. Vor dem Entfernen werden Nutzerfelder
(`sentAt`, `notes`, `contact`, `interviewDate`, `statusChangedAt`) übernommen,
Dokumentverweise zusammengeführt und ein weiter fortgeschrittener Status
gewinnt. Ein Lauf entfernte genau eine Waise; der versendete Eintrag blieb
unverändert (0 Feldverluste).

**Bewusst nicht angefasst.** 83 Zeilen tragen einen `firma|titel`-Schlüssel,
obwohl inzwischen eine URL bekannt ist. Sie umzuschlüsseln hieße, Primärschlüssel
zu verschieben — bei Nutzerdaten zu riskant für den Nutzen. Sie bleiben stabil.

**Testabdeckung.** `TestNormalize` in `tests/test_profile.py` (11 Fälle:
Strichvarianten, weiches Trennzeichen, URL-Gleichheit, echte Unterschiede).

## ADR-030 – Rollen-Signal: Berufsbezeichnungen auf -er sind keine Testrollen

`has_role_signal` prüft den Titel auf Test-/Absicherungswörter, darunter die
Domänenwörter `mechatronik`, `elektronik`, `elektrotechnik`. Mit `\w*` am Ende
matchte `\belektronik\w*` auch **„Elektroniker"**, weil „elektronik" ein Präfix
des Berufsnamens ist. Dasselbe galt für „Elektrotechniker" und
„Kfz-Mechatroniker".

Folge: Die Hilti-Anzeige **„Elektroniker"** galt als Testrolle und bekam bei
76 % Fit (erreicht über generische Wörter wie „prüfstände", „messtechnik",
„dokumentation") komplette Unterlagen. Es ist ein Fertigungsberuf.

*Fix.* Negatives Lookahead `(?!er)` an den drei Domänenwörtern. Damit bleiben
„Elektroniktests", „Elektrotechnik Ingenieur", „Mechatronik-Ingenieur" und
„Schwerpunkt Mechatronik" erlaubt (die beiden letzteren sind ausdrücklich
gewollte Treffer), während die Berufsbezeichnungen ausscheiden.

**Testabdeckung.** `test_matching.py`: 6 Berufsbezeichnungen ohne Signal,
5 Domänenwort-Titel mit Signal.

## ADR-032 – Qualitätsprüfung als eigener, unabhängiger Schritt

Der Review (P0b) verlangt eine Prüfung der erzeugten Unterlagen: Stimmen
Tätigkeiten, Zeiträume und Arbeitgeber mit dem Lebenslauf überein? Sind
Technologien nachweisbar? Werden die Anforderungen der Anzeige adressiert?
Gibt es erfundene Kompetenzen?

Bisher gab es dafür nichts. Die Generierung ist zwar deterministisch und zieht
Behauptungen aus dem Profil — aber niemand hat das Ergebnis *gegen* das Profil
geprüft. Ein Fehler in der Auswahl (falscher Bullet, falsche Station, alter
Arbeitgeber im Fließtext) wäre unbemerkt geblieben.

**Entscheidung.** `quality.py` prüft jede Bewerbung deterministisch gegen drei
Quellen und vergibt Schweregrade:

1. **Profil:** Jede Behauptung im Anschreiben muss als Beleg-Bullet im Profil
   stehen (Signaturvergleich), jeder Zeitraum muss im Profil vorkommen, jeder
   genannte Arbeitgeber/Projektkunde muss im Profil oder im Stellentitel stehen.
2. **Anschreiben:** Anrede, Betreff mit Stellentitel und Grußformel müssen
   vorhanden sein; bestätigte Lücken (`gap_terms`) müssen als
   Transparenz-Absatz ausgewiesen sein.
3. **Datei:** PDF existiert, beginnt mit `%PDF`, hat eine plausible Seitenzahl
   (Anschreiben ≤ 2).

Der Text wird bei der Generierung mitgeschnitten (`text_out`), nicht aus dem
PDF extrahiert — das spart eine zusätzliche Abhängigkeit. Für alte Unterlagen
ohne Text läuft nur die Dateiprüfung; `qualitaet.umfang` unterscheidet
`voll` von `datei`, und das Dashboard zeigt das an („Prüfung – Datei“ statt
„Prüfung ✓“).

**Kein LLM in dieser Stufe.** Die Prüfung soll nicht überzeugbar sein und
nichts kosten. Ein Modell-Check für Stil und Individualität ist eine mögliche
Ergänzung, aber kein Ersatz für „diese Zahl steht nicht im Profil“.

**Realdaten (25.10.2026).** 169 vorhandene Anschreiben neu gerendert und
geprüft: 0 Fehler, 0 Warnungen, 4 Hinweise (Anschreiben nennt keinen der
Kernbegriffe aus dem Titel — u. a. „Flight Test & Field Systems Engineer“).
Der Bestandslauf über 169 Bewerbungen fand 22 alte Bewerbungen, deren
PDF-Ordner aufgeräumt wurden — als Hinweis, nicht als Fehler, weil sie
versendet/abgelehnt sind.

**Grenzen.** Die Arbeitgeber- und Anforderungsprüfung sind Heuristiken mit
Stoppliste; ein englisches Anschreiben darf dieselbe Rolle anders benennen.
Deshalb sind sie Hinweis/Warnung, nie Fehler. Eine echte PDF-Textextraktion
fehlt bewusst (keine neue Abhängigkeit).

**Testabdeckung.** `test_quality.py`: erfundene Behauptung, falscher/richtiger
Zeitraum, fehlende Anrede/Grußformel, Arbeitgeber außerhalb des Profils,
Arbeitgeber im Bullet/Stellentitel, Lücke ohne Transparenz, Anforderungs-
Hinweis, PDF-Prüfungen (fehlt, kein PDF, zu viele Seiten), Zusammenfassung
fürs Dashboard.

## ADR-033 – Nachfassen als eigene Stufe, ohne Automatik

Der Bestand zeigt die Lücke: 120 versendete Bewerbungen, 8 Interviews, und
bis zuletzt keine Erinnerung an offene Fälle. Die Pipeline endete mit dem
Versand — der Teil, der über Antwortquoten entscheidet, fehlte.

**Entscheidung.**

1. `followup.py` bestimmt deterministisch fällige Bewerbungen: `sent` mit
   `sentAt` ≥ `followup.after_days` (Standard 14) oder `followup` mit
   `statusChangedAt` ≥ N Tagen (zweite Nachfrage). `interviewDate` schließt
   aus (es gab eine Reaktion), fehlende Daten führen zu keiner Fälligkeit.
2. Das Dashboard zeigt die Fälligkeit in der Status-Spalte, einen Filter und
   eine KPI-Karte. `agent.py followup [--days] [--write]` listet die Fälle;
   `--write` legt einen Text neben die Unterlagen (`Follow-up_de.txt`).
3. **Kein automatischer Versand, kein Statuswechsel.** Ob eine Nachfrage
   rausgeht, entscheidet der Nutzer; der Statuswechsel auf `followup` ist die
   Bestätigung, dass sie rausging — und startet die Frist für die zweite.

**Warum Textdatei statt PDF:** Eine Nachfrage ist eine E-Mail, kein Anhang.
Der Text wird in den Ordner gelegt, damit er neben dem Anschreiben liegt und
kopiert werden kann; ein PDF würde eine formelle Bewerbung suggerieren.

**Grenzen.** Die Frist ist eine Konvention (14 Tage), keine Norm — sie ist
per `followup.after_days` änderbar. Bewerbungen ohne `sentAt` werden nicht
geschätzt; sie erscheinen erst, wenn der Versand im Dashboard erfasst ist.

**Testabdeckung.** `test_followup.py`: Fristen (14/13 Tage), zweite
Nachfrage, Interview-Ausschluss, Löschung, Sortierung, DE/EN-Text,
Schreiben neben die Unterlagen, Dashboard-Flag und Filter.

## ADR-034 – Such-Quellen mit Historie und automatischer Abschaltung

Ausgangslage: Zwölf Quellen laufen in jedem Suchlauf mit. JobSpy/Indeed/Google
liefern seit Wochen 403, ohne dass das irgendwo gezählt wurde; ATS-Boards
drosseln gelegentlich. Ein Lauf „mit zwölf Quellen“ sah dadurch immer
erfolgreich aus, und ein stiller Ausfall war von „nichts Passendes gefunden“
nicht zu unterscheiden.

**Entscheidung.**

1. `provider_health.py` führt die Historie je Quelle in der SQLite-Meta-Tabelle
   (`provider_health`) — kein Schema-Umbau, keine Migration.
2. Ein Lauf zählt als **Fehler**, wenn er Fehlermeldungen liefert **und**
   nichts findet. Treffer trotz einzelner Fehler (StepStone: 2 von 28 Begriffen)
   sind ein Erfolg — sonst würde eine teilweise gestörte, aber nützliche Quelle
   abgeschaltet.
3. Nach `search.provider_health.max_failures` (Standard 3) Fehlläufen in Folge
   wird die Quelle deaktiviert und im nächsten Lauf übersprungen.
4. **Manuelle Reaktivierung** (`agent.py providers --enable NAME`), kein
   automatisches Wiedereinschalten: Eine fälschlich deaktivierte Hauptquelle
   würde sonst stillschweigend fehlen — genau der Fehler, den dieses ADR
   verhindern soll.
5. JobSpy fängt seine HTTP-Fehler intern ab und loggt sie nur. `search/jobspy.py`
   sammelt diese Log-Meldungen und wirft, wenn kein einziger Treffer ankam —
   sonst wäre die tote Quelle für die Statistik unsichtbar.

**Grenzen.** ATS wird als *eine* Quelle geführt (Board-Ebene wird nicht
getrennt); Fehler zählen pro Lauf, nicht pro Suchbegriff; die Historie beginnt
mit dem nächsten Suchlauf. Die Schwelle 3 ist eine Konvention, keine Messung.

**Testabdeckung.** `test_provider_health.py`: Erfolg/Fehler/Serie, Schwelle
konfigurierbar, Teilfehler mit Treffern, übersprungene Quelle zählt nicht,
manuelles Aus-/Einschalten, Reset, deaktivierte Quelle wird im Suchlauf nicht
aufgerufen, Fehler landet in der Statistik.

## ADR-035 – Fit-Score nachrechenbar: Rollen-Gate, Mehr-Standort, `word_hits`

Ausgangslage: Eine Anzeige „Lead Integration Engineer (m/w/d) im Team
Technology Consulting" stand mit **84 %** auf `docs`, obwohl sie
Integrationsarchitektur und Beratung beschreibt (Kafka, REST/SOAP, Middleware,
API-Governance) und keine Test-/Verifikationsrolle ist. Zerlegung:

    0 (Titel) + 52 (13 body_hits) + 22 (11 word_hits) + 10 (Ortsbonus) = 84

Drei unabhängige Ursachen, drei Korrekturen.

1. **Rollen-Gate.** `has_role_signal()` akzeptierte `\bintegration\w*` als
   Rollensignal — laut Kommentar bewusst, damit „Payload Integration Engineer"
   nicht herausfällt. Ergebnis: jede Architektur- oder Beratungsstelle mit
   „Integration" im Titel passierte das Gate. Neu: Wer zusätzlich ein
   Architektur-/Beratungswort trägt (`architekt|architect|consult|berat|presales`)
   **und** keinen Test-/Verifikationskern (`test|verification|validation|
   absicherung|erprobung|qualität|prüf`), passiert nicht mehr.
   `integration` bleibt im Rollen-Muster.
2. **Ortsbonus.** `location_bonus_for()` gab pauschal +10, sobald
   `pendel_modus == "Remote"` — und `bundesweit` steht in `_REMOTE_MARKERS`.
   Die Mehr-Standort-Angabe „bundesweit, Düsseldorf, …, München" wurde damit
   zur Remote-Stelle, obwohl der Einsatzort offen ist. Neu: Nennt der Ort
   mehrere Standorte **und** liegt mindestens einer außerhalb der
   Metropolregion, gibt es keinen Bonus. Land/Bundesland und Adressbestandteile
   (Hausnummer, PLZ) zählen nicht als Standort — „Garching b. Muenchen, Bayern,
   Germany" und „Landaubogen 1, 81373 München" bleiben je ein Ort, und
   „München, Starnberg" behält den Bonus, weil beide Orte im Umkreis liegen.
3. **`word_hits` wurde nie gespeichert.** Die Punktzahl floss in den Score
   (`2 * len(word_hits)`), war aber in `score_fields` nicht enthalten — kein
   Eintrag im Bestand konnte nachgerechnet werden. `score_job()` liefert die
   Liste jetzt (sortiert, JSON-fähig) und `_merge_state()` übernimmt sie.

**Verworfene Variante.** `\bintegration\w*` ersatzlos zu streichen hätte 17
Einträge durch das Gate fallen lassen, darunter „Senior Payload Integration
Engineer" (100 %), „HW/SW Integration Engineer" (78 %) und „R&D Engineer -
AI Integration" (72 %) — ausdrücklich gesuchte Rollen. Die gemessene Variante
ändert 2 Einträge: die x1F-Beratungsstelle und „Systems Architect ECU
Autonomous Driving".

**Grenzen.**
- Das Gate blockiert nur die automatische Unterlagen-Erzeugung; bestehende
  Einträge und ausdrückliche `generate --ids` bleiben unberührt.
- Der Ortsbonus ist weiterhin eine Textheuristik, keine Fahrzeit. Wo eine
  berechnete Pendelzeit vorliegt, gilt sie unverändert.
- `word_hits` sind eine Teilmenge der `body_hits`; derselbe Treffer zählt also
  4 + 2 = 6 Punkte. Das ist gewollt (weiches Signal), aber im Score sichtbar.

**Testabdeckung.** `test_scoring_gates.py`: Beratungs-/Architekturtitel fallen
durch, Payload-/HW-SW-/AI-Integration und „Test-Architekt" bleiben; Mehr-Standort
vs. Adresse/nahe Orte; Bonus 0 für Fernorte, 10 für echte Remote-Stellen;
`word_hits` wird geliefert, der Score ist aus den Teilen nachrechenbar, und
`_merge_state` übernimmt das Feld.

## ADR-038 – Fit-Deckel bei komplett fremdem Technologie-Stack

Ausgangslage: Die Stelle „Lead Integration Engineer (m/w/d) im Team Technology
Consulting" (x1F) erreichte 74 %. Die Anzeige verlangt Java, Spring Boot,
Kafka, SOAP, SQL, Docker, Postman, SoapUI, Grafana und Guidewire — nichts
davon ist im Profil belegt. Der hohe Wert entstand aus generischen Wörtern:
„Integration", „Schnittstellen", „Anforderungen", „Testen", „Debugging" — alles
Begriffe, die auch eine Testrolle beschreiben. Der Rollen-Gate (ADR-035)
verhindert inzwischen die automatische Unterlagenerzeugung, aber der Fit-Wert
selbst behauptete weiterhin eine hohe Passung.

**Entscheidung.** `matching.score_job` gleicht den in der Anzeige genannten
Technologie-Stack gegen die **belegten** Kompetenzen ab (`stack_gap`). Sind
mindestens drei Stack-Begriffe genannt und **keiner** davon im Profil belegt,
und enthält der Titel keinen Test-/Verifikationskern (`_TEST_KERN_RE`), wird
der Score auf **60 %** gedeckelt. Die Begründung nennt den Deckel und die
fehlenden Begriffe.

**Warum 60:** unter dem Research-Fenster (65), über der Ausblendegrenze (50).
Die Stelle bleibt auffindbar und nachvollziehbar, ist aber kein Research- oder
Bewerbungsfall. Der Deckel ist keine Aussage über die Person, sondern über die
Passung zur konkreten Anzeige.

**Warum mindestens drei Begriffe:** Eine Anzeige, die nur MATLAB nennt
(Embedded-Rolle mit CAN/AUTOSAR), ist kein Ausschluss — ein einzelner
Werkzeugname neben passendem Profil ist eine Einarbeitung. Erst wenn der
genannte Stack überwiegend fremd ist, trägt die Keyword-Überschneidung nicht.

**Warum nur ohne Test-Kern im Titel:** Testrollen in Java-/Kafka-Umgebungen
bleiben unangetastet. Wer eine Java-Anwendung testet, muss sie nicht
implementieren; der Stack ist dort Umgebung, nicht Eignung.

**Belegquelle:** `Profile.evidence_text` (Skills, Berufserfahrung, Ausbildung,
Zertifikate) — bewusst **ohne** `_meta`, `gap_terms` und
`confirmed_gaps_do_not_overclaim`. Dort stehen Technologien, die gerade
*fehlen* („Keine Docker-Erfahrung"); ein Abgleich gegen den vollen JSON-Text
würde diese Lücken als Kompetenz zählen.

**Grenzen.** Die Begriffstabelle (`_STACK_TERMS`) ist bewusst klein und
endlich; sie deckt die üblichen Sprachen, Frameworks, Messaging-, Datenbank-,
Container- und Plattformbegriffe ab. `REST` fehlt absichtlich, weil „der Rest"
im Deutschen zu häufig ist. Neue Begriffe werden nur mit Test aufgenommen.

**Folgen.** Drei bestehende Einträge wurden am 25.10.2026 nachträglich
korrigiert: x1F Lead Integration Engineer 74 → 60, Upflow Senior Full Stack
Engineer 68 → 60, AlmavivA Backend Developer .NET 66 → 60. Alle übrigen
Scores blieben unverändert.

**Testabdeckung.** `test_scoring_stack.py`: Stack-Erkennung, belegter Begriff,
Lückenlisten zählen nicht als Beleg, Deckel bei Architekturrolle, kein Deckel
bei Testrolle, bei teilweise belegtem Stack, ohne Stack und bei nur einem
genannten Begriff.

## ADR-039 – Rollen-Gate für Entwicklerstellen, historische Bewertungen eingefroren

Ausgangslage: Die Spitze der Trefferliste war voll von Entwicklerrollen —
„Principal Engineer – AI-Enabled Embedded Software" (NXP) 100 %,
„Senior Manager CAD Infrastructure" (Infineon) 100 %, „Firmware-Entwickler
Embedded Systems" (ALPHA LASER) 98 %. Der Keyword-Fit belohnt die
Domänenüberschneidung (Embedded, Software, AI), nicht die ausgeübte Rolle:
Das Profil beschreibt Test, Absicherung und Integration, nicht Produktentwicklung.

**Entscheidung.**

1. `matching.is_development_role(title)` erkennt Entwickler-/Produktrollen:
   ein Domänenwort (Software, Firmware, Embedded, Backend, Frontend, Cloud,
   DevOps, Data/ML/AI, Robotik, Chip/FPGA, CAD) **und** ein Rollenwort
   (Entwickler, Developer, Engineer, Ingenieur, Architekt, Designer, Manager,
   Leiter, Lead, Head) im Titel. Fehlt ein Test-Kern im Titel, wird der Score
   auf **60 %** gedeckelt (`role_cap`).
2. Der Test-Kern hat Vorrang: „Software Test Engineer", „Testingenieur Embedded
   Software" und „Entwicklungsingenieur Testsysteme" bleiben unangetastet.
   „Systemingenieur" und „Integrationsingenieur" ebenso — dort fehlt ein
   Domänenwort.
3. **Historische Bewertungen bleiben stehen.** `_merge_state` überschreibt die
   Score-Felder nicht mehr, wenn der Status `sent`, `followup`, `interview`
   oder `rejected` ist. Eine versendete Bewerbung behält den Fit zum
   Entscheidungszeitpunkt.

**Warum das Einfrieren:** Die Evaluation (`eval/`) lernt aus echten
Entscheidungen. Würde ein neues Gate alte Bewerbungen rückwirkend auf 60 %
setzen, verschöben sich die Labels — und die Aussage „AUC 0,715" wäre nicht
mehr mit derselben Datenbasis vergleichbar. Außerdem sieht eine bereits
versendete Bewerbung sonst wie eine Fehlentscheidung aus, obwohl sie zum
damaligen Zeitpunkt begründet war.

**Grenzen.** Das Gate arbeitet nur auf dem Titel; eine Anzeige
„Softwareentwickler (m/w/d) Testsysteme" bleibt erlaubt, obwohl sie Entwicklung
ist. Die Domänenliste ist endlich und muss bei Bedarf erweitert werden.

**Folgen (25.10.2026 gemessen).** Von 275 sichtbaren Stellen fallen 31 durch das
Gate, davon 25 mit Status `neu` (NXP 100 → 60, Infineon 100 → 60, ALPHA LASER
98 → 60, MTU 96 → 60 …). Sechs bereits versendete/abgelehnte Bewerbungen
behalten ihren historischen Wert.

**Testabdeckung.** `test_scoring_roles.py`: sieben Titelerkennungen (inkl.
Test-Kern-Ausnahmen), fünf Score-Fälle (Deckel bei Embedded/CAD, kein Deckel
bei Test-/Systemrollen). Der Einfrier-Mechanismus wird über den Live-Lauf
verifiziert (sechs historische Einträge unverändert).

## ADR-040 – Diehl als ATS-Quelle, Firmen-Aliase, täglicher Mail-Abgleich

Ausgangslage: Der Gmail-Abgleich am 26.10.2026 zeigte sieben Leads, die der
Agent nie gefunden hatte. Vier lagen außerhalb des 30-Minuten-Radius (Ulm,
Egelsbach, Donauwörth, Dresden), zwei waren Recruiter-Anzeigen (SEG MUC,
SThree), eine war eine echte Lücke im Radius. Zusätzlich fehlte Diehl Aviation
komplett als Quelle, obwohl dort regelmäßig passende Stellen stehen.

**Entscheidungen.**

1. **Diehl-Provider** (`ats: "diehl"`): Die Karriereseite ist eine
   TYPO3-Jobbörse mit serverseitig gerenderter Liste (`?p=N`, 12 je Seite,
   `?d=4` filtert Diehl Aviation). Titel, Bereich, Ort und URL stehen im
   Listen-HTML; Detailseiten liefern die Abschnitte als
   `<h2>…</h2><div class="ezrichtext-field">…</div>`. Detailseiten werden nur
   für Stellen im Umkreis geladen. Ergebnis im Test: 6 Stellen im Umkreis von
   111 Diehl-Aviation-Anzeigen, Beschreibungen 900–2.100 Zeichen.
2. **Firmen-Aliase** (`matching.company_aliases`): Die Identitätsprüfung
   entfernt jetzt Rechtsformen (GmbH, AG, SE …) und bildet konfigurierte
   Aliase ab. „NXP Semiconductors" und „NXP" sind damit dieselbe Anzeige —
   vorher blieb ein Duplikat bei 100 %, während das andere über das Rollen-Gate
   auf 60 % fiel. Schlüssel werden normalisiert erwartet (`nxp semiconductors`).
   Recruiter→Endkunde lässt sich nur eintragen, wenn der Endkunde bekannt ist;
   der Mail-Abgleich meldet solche Leads separat, statt sie als „nie gefunden"
   zu zählen.
3. **Täglicher Mail-Abgleich** (`bewerbung_mailcheck.py`, Cron 07:40): liest
   JobLeads- und StepStone-Jobagent-Mails der letzten zwei Tage, extrahiert
   Firma/Titel und prüft gegen `data/jobs.json` und `data/state.json`. Ausgabe:
   Anzahl Leads, gefunden/offen/Recruiter, Liste der offenen. Der Abgleich ist
   bewusst streng (Firma + vier gemeinsame Wörter oder Titelähnlichkeit ≥ 0,85),
   weil ein falsches „gefunden" eine echte Lücke verdeckt.
4. **Absagen-Abgleich im selben Lauf**: Der Mailcheck sucht zusätzlich nach
   Absageformulierungen („nicht weiter berücksichtigen", „leider müssen wir",
   „unfortunately" …) der letzten sieben Tage. Eindeutige Treffer werden über
   `scripts/apply_status.py` (Projekt-venv, `Store.apply_overlay`) auf
   `rejected` gesetzt, Datum = Mail-Datum, Notiz mit Absender. Zugeordnet wird
   nur, wenn Firma (voller Name im Text oder Domain-Token) und — falls genannt —
   die Stelle passen; der Bewerbungstitel darf keine Zusatzbegriffe haben
   („TOSCA Test Automation Engineer" ist nicht „Test Automation Engineer").
   Mehrere offene Bewerbungen bei derselben Firma ohne Stellenangabe bleiben
   **unklar** und werden nur gemeldet. Gmail-Quota: 1,2 s Takt und Backoff bei
   `rateLimitExceeded` (250 Einheiten/Minute).

**Grenzen.** Der Mailcheck lebt in `~/AppData/Local/hermes/scripts/`, nicht im
Repo: er braucht die Google-Bibliotheken der Hermes-Umgebung. Die
Recruiter-Erkennung ist eine Namensliste; neue Recruiter müssen ergänzt werden.
Diehl-Seiten sind englisch/deutsch gemischt; die Beschreibung wird als Klartext
übernommen.

**Testabdeckung.** `test_identity_alias.py`: Rechtsform-Normalisierung,
Alias-Zusammenführung, Identität mit/ohne Alias. Der Diehl-Provider wurde live
gegen die Karriereseite getestet (6 Treffer, Beschreibungen vorhanden).

## ADR-041 – C++ ist eine bestätigte Lücke, `hard_gaps` deckeln Titel-Nennungen

Ausgangslage: Das Profil führte „C++ (Grundkenntnisse)" in zwei Skill-Listen
und im kombinierten Profil. Der Nutzer hat am 28.10.2026 klargestellt, dass
**keine** C++-Kenntnisse vorliegen. Damit waren alle C++-Treffer im Scoring
falsch: Sie gaben Titel- (×6) und Textpunkte (×4) für eine Qualifikation, die
es nicht gibt — 46 sichtbare Stellen nannten C++, mehrere standen bei 100 %.

**Entscheidungen.**

1. **Profil bereinigt:** C++ aus `skills.programmierung` und
   `skills.hardware_embedded_chip` entfernt, `kombiniertes_kompetenzprofil`
   angepasst, `confirmed_gaps` präzisiert („Keine C++-Kenntnisse, explizit
   28.10.2026"). Backups: `Profil-Datenbank.json.bak-vor-cpp`.
2. **`matching.hard_gaps`** (Standard `["C++"]`): Steht ein konfigurierter
   Begriff im **Titel** und ist er im Profil nicht belegt, wird der Score auf
   **60 %** gedeckelt (`hard_gap`). Begriffe: C++, C#, Java.
3. **Belegquelle `Profile.evidence_raw`**: unnormalisierter Skill-Text, weil
   `normalize("C++")` nur „c" übrig lässt und der Vergleich sonst nicht
   funktioniert.

**Warum nur der Titel:** C++ im Fließtext ist oft eine Umgebungsangabe
(„Tests in C++-Codebasis") und keine Einstellungsvoraussetzung. Dort wirkt
bereits der normale Punkteverlust, weil C++ keine Keywords mehr beiträgt.

**Folgen (28.10.2026 gemessen).** 33 aktive Einträge neu bewertet; drei
C++-Titel fallen auf 60 % (Softwareentwickler C++/Qt bei Free resume und
ALTEN). Beispiele für den Punkteverlust durch die Profilbereinigung:
Rohde & Schwarz 100 → 96, Neilsoft 96 → 84, MicroNova 94 → 90,
ICT Digital 90 → 82. Bereits versendete/abgelehnte Bewerbungen bleiben
eingefroren (ADR-039).

**Grenzen.** Neue bestätigte Lücken müssen in `matching.hard_gaps` eingetragen
werden; die Regex-Tabelle kennt nur C++, C# und Java. „C/C++" im Titel wird
durch `\bc\+\+` erkannt, „C" allein nicht.

**Testabdeckung.** `test_scoring_hardgap.py`: Deckel bei C++ im Titel,
kein Deckel ohne `hard_gaps`, kein Deckel bei C++ nur im Text, kein Deckel bei
belegtem C++.

## ADR-042 – Gleiche Firma + gleicher Titel gilt für beworbene Rollen als eine Stelle

Ausgangslage: MicroNova erschien sechsmal im Dashboard — dieselbe Anzeige
(„Produktmanager Testautomatisierung"), von Glassdoor unter München, Dachau und
Freising geführt, teils zusätzlich als „Product Owner". Die Identitätsprüfung
nutzt Firma + Titel + **Ort**, deshalb blieben alle Varianten stehen; eine war
sogar schon versendet, die übrigen fünf standen als `docs` daneben.

**Entscheidung.** `_merge_state` überspringt neue Treffer, wenn Firma und Titel
exakt einer bereits **beworbenen** Rolle entsprechen (`sent`, `followup`,
`interview`) — unabhängig vom Ort. Für nicht beworbene Einträge bleibt der Ort
Teil der Identität, weil dieselbe Rolle an zwei Standorten zwei echte Stellen
sein kann.

**Datenbereinigung.** Die sechs MicroNova-Einträge wurden am 28.10.2026 auf
einen reduziert: der versendete Eintrag bleibt, heißt jetzt „Produktmanager
(m/w/x) Testautomatisierung", steht in Vierkirchen (hybrid) und trägt die
Glassdoor-Bezeichnung als Notiz. Die fünf Dubletten sind mit
`deleted_reason = "Dublette: dieselbe Stelle (MicroNova, Vierkirchen)"`
gelöscht; ihre Dateien bleiben liegen.

**Grenzen.** Die Regel greift erst nach dem Versand. Vorher können
Location-Varianten weiterhin mehrfach erscheinen; sie werden nur über die
normale Identitätsprüfung (Firma + Titel + Ort) zusammengeführt.

**Testabdeckung.** `test_pipeline_dedupe.py`: gleiche beworbene Stelle mit
anderem Ort wird übersprungen, andere Firma bleibt eigener Eintrag, ohne
Bewerbung bleibt der Ort identitätsstiftend.

## ADR-043 – Python ist Grundkenntnis: `weak_skills` geben keine Fit-Punkte

Ausgangslage: Das Profil führte „Python (erweiterte Grundkenntnisse)" und einen
Satz über ein „eigenes Python-basiertes Testautomatisierungstool". Beides war
zu hoch gegriffen: Nur Grundkenntnisse, kleine Skripte, kein eigenständig
entwickeltes Tool. Python zählte im Scoring als Titel- (×6), Text- (×4) und
Worttreffer (+2) und hob Stellen mit Python-Nennung um bis zu sechs Punkte.

**Entscheidungen.**

1. **Profil korrigiert:** „Python (Grundkenntnisse)" in beiden Skill-Listen,
   kombiniertes Profil auf „Python-Grundkenntnisse für kleine Skripte", die
   Lücke präzisiert („kein eigenständig entwickeltes Tool, kleine Skripte,
   bestätigt 28.10.2026"). Backup:
   `Profil-Datenbank.json.bak-vor-python`.
2. **`matching.weak_skills`** (Standard `["Python"]`): Begriffe aus dieser Liste
   werden aus Titel-, Text- und Inhaltswort-Treffern entfernt. Sie bleiben im
   Profil und in den Unterlagen sichtbar, tragen aber keinen Fit bei.
3. Der frühere Werkzeug-Satz in der Berufserfahrung war bereits durch die
   parallele Sitzung auf „mit Python-Skripten" korrigiert worden.

**Warum ganz entfernen statt halb gewichten:** Das Scoring rechnet mit ganzen
Punkten (6/4/2). Eine Halbgewichtung wäre eine Scheingenauigkeit; „zählt nicht
als Alleinstellungsmerkmal" ist die ehrliche Aussage für Grundkenntnisse.

**Folgen (28.10.2026 gemessen).** 17 offene Einträge neu bewertet, jeweils
−6 Punkte, weil Python-Treffer wegfielen. Beispiele: Rohde & Schwarz 96 → 90,
ALTEN Wellenform 80 → 74, NXP Digital IP 76 → 70, INGSERV 76 → 70,
Infineon Digital Concept 74 → 68, Renesas Business Development 70 → 64,
STARK Automation Engineer 68 → 62. Sichtbar: 252 Stellen, 140 ≥ 65 %,
98 ≥ 71 %. Versendete/abgelehnte Bewerbungen bleiben eingefroren.

**Unterlagen (28.10.2026).** Alle 16 offenen Bewerbungen wurden neu erzeugt
(DE/EN, Anschreiben + Lebenslauf). Dabei fiel ein Fehler auf:
`_generate_one` übernahm `matched_skills` aus dem gespeicherten Eintrag — dort
standen noch die Treffer des alten Profils (inkl. C++). Jetzt werden die
Treffer für die Unterlagen aus dem **aktuellen** Profil gerechnet, ohne
`weak_skills`. Zusätzlich korrigiert: „C/C++ & Python" aus den
Fallback-Schwerpunkten (`_CHIP_SUMMARY`) entfernt und die CV-Kompetenzkarte
„& Python-Tools" auf „& Testskripte" geändert. Prüfung mit pypdf: 0 von 16
Unterlagen nennen noch C++, „erweiterte Grundkenntnisse" oder ein eigenes
Python-Tool; die Skill-Zeile lautet „Python (Grundkenntnisse) · Scripting
(Python, Bash)".

**Grenzen.** Die Liste ist statisch; neue Grundkenntnisse müssen eingetragen
werden. Python verschwindet nicht aus dem Profil — Lebenslauf und Anschreiben
nennen es weiterhin, nur der Fit bewertet es nicht.

**Testabdeckung.** `test_scoring_weak.py`: Python gibt keine Punkte, Stellen
ohne Python bleiben unverändert, andere Begriffe zählen weiter.

## ADR-044 – Software-Entwicklungsrollen werden auf 45 % gedeckelt

Ausgangslage: „Softwareingenieur für Embedded Software" (HENSOLDT, 62–66 %),
„Embedded Softwareentwickler" (ICT Digital, 82 %) und „Softwareentwickler
C++ / Qt" (ALTEN, 60 %) standen im Dashboard, obwohl sie Produktcode-Entwicklung
verlangen. Der bestehende Rollen-Deckel (ADR-039) griff bei vielen davon nicht:
`_DEV_ROLE_RE` verlangte eine Wortgrenze vor „ingenieur"/„entwickler" und
übersah damit genau die deutschen Komposita („Software**ingenieur**",
„Software**entwickler**").

**Entscheidungen.**

1. **Komposita greifen:** Die Rollenwörter stehen ohne führende Wortgrenze
   (`entwickler\w*|ingenieur\w*`), Domänenwörter bleiben mit `\b` verankert.
   Damit erkennt `is_development_role` auch „Softwareingenieur" und
   „Softwareentwickler".
2. **Neue Rolle `is_software_role`:** Software-Domäne (Software, Firmware,
   Backend, Frontend, Full-Stack, Cloud, DevOps, Web, Mobile, Android) plus
   Entwicklerrolle, ohne Test-Kern im Titel.
3. **`SOFTWARE_CAP = 45`** liegt unter der Ausblendegrenze (50): Diese Stellen
   verschwinden aus Dashboard und Research, bleiben aber in der Datenbank.
   Hardware-/Embedded-Entwicklung bleibt bei 60 (ADR-039).
4. **Keine `app`-Domäne:** Ein erster Versuch nahm `\bapp\w*` auf — damit
   wurden „Applications Engineer" und „Field Applications Engineer" (TI,
   Renesas, IC Resources) fälschlich zu Software-Rollen und fielen von 72 auf
   45. Die Domäne ist wieder entfernt; ein Test sichert das ab.

**Folgen (28.10.2026 gemessen).** 13 offene Einträge neu bewertet, davon neun
Software-Rollen auf 45: ICT Digital 82 → 45, Itsicherheit 68 → 45,
HENSOLDT 66/62/62 → 45, Free resume 60 → 45, ALTEN 60 → 45 (×2),
Bertrandt 60 → 45. Vier Field-Applications-Rollen wurden nach der
`app`-Korrektur zurückgesetzt (TI 72, Renesas 72, IC Resources 72,
Infineon 66). Sichtbar: 252 Stellen, 137 ≥ 65 %, 97 ≥ 71 %. Versendete und
abgelehnte Bewerbungen bleiben eingefroren.

**Testabdeckung.** `test_scoring_software_role.py`: Komposita werden erkannt,
„Software Test Engineer" und „Softwareentwickler für Testsysteme" bleiben
erlaubt, „Applications Engineer" ist keine Software-Rolle, Score-Deckel 45.

## ADR-045 – Dubletten: Gender-Tags, Titel-Synonyme, keine gelöschten Karten

Ausgangslage: Nach dem Zusammenführen der MicroNova-Einträge standen im
Dashboard wieder sechs Karten für dieselbe Stelle, obwohl fünf Einträge
`deleted` waren. Zwei Ursachen:

1. **Anzeige:** `dashboard_applications` prüfte `deleted` nicht. Einträge mit
   Status `docs` und vorhandenen PDFs kamen über die Unterlagen-Regel zurück in
   die Tabelle — die Dubletten hatten ja Dateien.
2. **Identität:** `_identity` verglich den Titel roh. „Produktmanager (m/w/x)
   Testautomatisierung" (Firmenseite) und „Product Owner Testautomatisierung
   m/w/d" (Glassdoor) sind textlich verschieden, also legte jeder Lauf neue
   Einträge an — trotz der Regel „gleiche Firma + gleicher Titel = dieselbe
   Stelle" (ADR-042).

**Entscheidungen.**

1. `dashboard_applications` überspringt gelöschte Einträge grundsätzlich.
2. `_title_key` entfernt Gender-Tags (`(m/w/x)`, `(m/w/d)`, `(all genders)`)
   und ersetzt Titel-Synonyme aus `matching.title_synonyms`
   (Standard: `product owner` → `produktmanager`). `_identity` und das
   `beworben`-Set nutzen diesen Schlüssel.
3. `_merge_state` vergibt eindeutige IDs: IDs kamen aus dem Match-Lauf (1..n)
   und kollidierten zwischen Läufen — 1.102 von 1.828 Einträgen hatten eine
   doppelte ID. Dokument- und Statuspfade adressieren über `key`; eindeutige
   IDs verhindern, dass ein Aufruf mit `id` den falschen Eintrag trifft (genau
   das passierte beim Erzeugen der MicroNova-Unterlagen).

**Folgen (30.10.2026).** Live-Bestand: 1.828 Einträge, 1.828 eindeutige IDs,
Dashboard 218 Zeilen, **eine** MicroNova-Karte (94 %, `sent`). Die fünf
Dubletten bleiben als `deleted` in der Datenbank, ihre Ordner bleiben liegen.

**Testabdeckung.** `test_identity_alias.py`: Gender-Tags zählen nicht,
`product owner`/`produktmanager` führen zusammen. `test_dashboard_visibility.py`:
gelöschte Stelle mit Unterlagen bleibt verborgen.

## ADR-046 – Mehrdeutige Ortsnamen: der nächste Treffer gewinnt

Ausgangslage: Die MicroNova-Stelle in **Vierkirchen** (85256) stand mit
**529 km / 306 min** Pendelweg im Dashboard. Nominatim hatte „Vierkirchen" auf
den gleichnamigen Ort in Sachsen (Reichenbach/O.L.) aufgelöst — 396 km statt
20 km Luftlinie. Bei „München Area" fand der Geocoder eine Straße in Sibiu
(980 km); 22 Airbus-Einträge wurden dadurch als „Pendelweg > 30 min" verworfen.

**Entscheidungen.**

1. `_Geocoder.geocode_near(query, home)`: bis zu fünf Nominatim-Treffer holen
   und den nächstgelegenen innerhalb von 150 km nehmen; der Treffer
   überschreibt den falschen Cache-Eintrag (`remember`).
2. `enrich_commute` prüft nach dem Geocoding: Liegt der Punkt mehr als
   `_AMBIGUOUS_KM` (150 km) entfernt, wird `geocode_near` versucht.
3. `_strip_noise` entfernt Regionsangaben ohne Ort („München Area",
   „Region München", „München Umgebung", „Raum München"), bevor geokodiert
   wird.

**Folgen (30.10.2026).** MicroNova Vierkirchen: 306 min/529 km → **29 min/30 km**.
68 Einträge über 100 km neu geprüft; 22 „München Area"-Einträge (Airbus) liegen
jetzt bei 25 min, drei weitere (Feldkirchen, Kirchheim) bei 16–17 min.
`run_enrich` hat 24 zu Unrecht verworfene Einträge wieder sichtbar gemacht.
Bestand: 233 sichtbar, 137 ≥ 65 %, Dashboard 218 Zeilen.

**Testabdeckung.** `test_commute_ambiguous_places.py`: Regionsangaben werden
entfernt, Vierkirchen/Bayern liegt < 40 km, Vierkirchen/Sachsen > 300 km,
`_nearest` wählt den nächstgelegenen Punkt.

## ADR-047 – Eine Quelle: Profil-Markdown wird aus der JSON erzeugt

Ausgangslage: Das Profil lag zweimal vor — als `Profil-Datenbank.json` (Quelle
für Matching und Unterlagen) und als handgepflegte Obsidian-Notiz
`Berufsprofil – Faktenbasis.md`. Beide liefen auseinander: Die Notiz nannte am
30.10. noch „Python (erweiterte Grundkenntnisse)" und „C++ (Grundkenntnisse)",
während die JSON bereits korrigiert war.

**Entscheidung.** Die JSON bleibt die einzige Quelle. Die Markdown-Datei ist
ein erzeugtes Artefakt:

1. `bewerbungsagent/profile_export.py` rendert die Lesefassung deterministisch
   (Person, Kompetenzmatrix, Berufserfahrung, Ausbildung, Lücken, Tailoring).
   Die Tailoring-Regeln stehen dafür als `tailoring_rules` in der JSON.
2. `agent.py profile-export` schreibt die Datei, `--check` prüft sie und
   liefert Exit 1 bei Abweichung (für Cron/CI).
3. `run_enrich` ruft den Export am Ende automatisch auf, wenn
   `profile_markdown` konfiguriert ist — Fehler dort brechen den Lauf nicht ab.
4. Der Kopf der Datei sagt „Automatisch erzeugt — nicht hier bearbeiten";
   `created` bleibt beim Überschreiben erhalten.

**Warum nicht die Markdown-Datei löschen:** Sie ist die lesbare Fassung im
Second Brain (Verlinkung, Callouts) und wird jetzt ohne Handarbeit aktuell
gehalten. Zwei *handgepflegte* Fassungen wären das Problem, nicht zwei
Darstellungen derselben Quelle.

**Testabdeckung.** `test_profile_export.py`: Render enthält Person,
Kompetenzmatrix, Lücken und nummerierte Tailoring-Regeln; Render ist
deterministisch; Export setzt `stale` auf False; eine JSON-Änderung macht die
Datei veraltet; `created` bleibt erhalten.

## ADR-048 – Markensuchen laufen im Tageslauf mit

Ausgangslage: Der Tageslauf führte genau eine Suche aus (`search.query_terms`).
Die neue Markensuche „China-EV München" (BYD, NIO, XPeng, Xiaomi, Leapmotor,
Li Auto) lief separat über `agent.py search "China-EV München"` — und
überschrieb dabei `jobs.json` mit einem 187-Stellen-Bestand, der die
Standard-Suche verdrängte. Zwei Läufe, zwei Bestände, ein Konflikt.

**Entscheidung.**

1. Eine gespeicherte Suche kann `"daily": true` tragen. `run_searches()` führt
   die Standard-Suche **und** alle Tageslauf-Suchen aus, führt die Treffer über
   die URL zusammen und schreibt **einen** Bestand nach `jobs.json`.
2. `run_full()` ruft `run_searches()` statt `run_search()` auf — match, enrich,
   generate und dashboard laufen danach wie bisher genau einmal.
3. `"ats_firmen"` beschränkt den `ats`-Provider auf die Karriereseiten der
   jeweiligen Suche. Ohne Filter zog die Markensuche alle 14 Boards mit (627
   Funde, 2 zur Frage).
4. `agent.py searches` markiert Tageslauf-Suchen.

**Folgen.** Die Markensuche kostet im Tageslauf zusätzlich rund zwei Minuten
(StepStone drosselt) und bringt derzeit 1–2 BYD-Stellen; die übrigen Marken
haben in München aktuell keine über die Börsen lesbaren Stellen. Der XPeng-
Greenhouse-Board ist angebunden und liefert neue München-Rollen automatisch.

**Testabdeckung.** `test_tageslauf_suchen.py`: Standard plus `daily`-Suchen in
der richtigen Reihenfolge, Board-Auswahl wird durchgereicht, ohne `daily` bleibt
nur die Standard-Suche. `test_search_board_filter.py`: Board-Filter.

## ADR-049 – Dashboard-Server abgeschottet, Zeitstempel korrigiert

Ausgangslage (Review vom 01.11.2026): Der lokale Dashboard-Server schickte
`Access-Control-Allow-Origin: *` und lieferte den kompletten Ordner
`2026/` statisch aus. Jede im Browser offene Webseite konnte damit
`04_Agent/config.json` (Wohnadresse, Tokens), `/state` (Status, Kontakte,
Notizen) lesen und per POST überschreiben — `text/plain` braucht keinen
Preflight. Zusätzlich wurde bei „laden → ändern → speichern" der alte
`updated`-Wert fortgeschrieben.

**Entscheidungen.**

1. **CORS nur für die eigene Herkunft**: `http://127.0.0.1:8766`,
   `http://localhost:8766` und `null` (Dashboard per `file://`). Kein `*`.
2. **Host-Prüfung** gegen DNS-Rebinding (`127.0.0.1:8766`, `localhost:8766`);
   fremder Host → 403.
3. **Sperrliste**: `04_Agent/config*`, `04_Agent/data/`, `.git`, `*.db`,
   `*.db-wal`, `*.db-shm`, `.env`, `*.bak` werden nie statisch ausgeliefert
   (404), auch per `HEAD` nicht.
4. **POST-Grenze** 5 MB; `Store` wird einmal pro Prozess angelegt statt pro
   Request (vorher sammelten sich SQLite-Verbindungen).
5. **`db.save_state`** schreibt immer `now_iso()` — nicht den `updated`-Wert
   aus dem geladenen Zustand (der fehlte bei `_record_docs`/`quality` ganz).
6. Kleinere Punkte: kaputte Nominatim-Antwort bricht den Enrich-Lauf nicht mehr
   ab, `zip(..., strict=True)`, Imports sortiert, Docstring nannte 65 % statt
   der Unterlagen-Schwelle.

**Betrieb.** Der Server lief vierfach (zwei alte Python-3.12-Prozesse lauschten
auf 8766, zwei neue konnten wegen `SO_REUSEADDR` ebenfalls binden). Alle
Prozesse beendet, ein neuer gestartet. Live geprüft: Dashboard 200,
`config.json` 404, `data/` 404, `/state` 200, fremde Origin 403, fremder Host
403, CORS-Header nur für die eigene Origin.

**Testabdeckung.** `tests/test_server_security.py` (11 Tests, startet den
Server echt), `test_scoring_roles.py` an den 45-%-Software-Deckel angepasst.
Lokal 173+ Tests grün, inklusive der SQLAlchemy-Suite.

## ADR-050 – Erledigte Absagen und Zwischenmeldungen bleiben im Digest still

**Problem.** Zwei Meldungen aus dem Mailcheck waren nicht falsch, aber
irreführend. (1) Eine Absage, die manuell auf `rejected` gezogen wurde (real:
Quantum-Systems „Test Automation Engineer", 04.11.2026), stand danach jeden Tag
erneut als „unklar" im Bericht — `match_mail` sieht nur *offene* Bewerbungen,
also fand sie nichts mehr. (2) Fortschritts-Mails („CV an die Fachabteilung
weitergeleitet") liefen unter der Überschrift „Einladungen / Zusagen" und lasen
sich wie ein Terminwunsch. Dazu kam bei nicht zugeordneten Mails immer
„keine passende Bewerbung im Bestand" — der echte Grund („2 offene Bewerbungen
passen zum Titel", also eine Dublette) war nur im JSON sichtbar.

**Entscheidung.**

1. `auswerten` prüft, bevor es eine Absage als unklar meldet, ob genau diese
   Firma+Titel bereits `rejected` ist. Dann zählt die Mail als
   `schon_erfasst` (das Feld stand schon im Docstring, war aber nie
   implementiert) und verschwindet aus dem Bericht. Der Zähler erscheint in der
   Kopfzeile von `agent.py absagen`.
2. `positives(...)` schreibt den Zuordnungsgrund in den Hinweis:
   „keine passende Bewerbung im Bestand (*warum*)".
3. Der Hermes-Mailcheck trennt „Fortschritt im Prozess" von „Einladungen /
   Zusagen" (`art == "fortschritt"`).

**Nicht geändert.** Die Zuordnungsregeln selbst (`titel_passt`,
`firma_passt`, 80-%-Grenze) bleiben streng: lieber unklar melden als falsch
buchen. Zwischenmeldungen werden weiterhin gemeldet — sie sind der Hinweis,
dass der Prozess läuft.

**Betrieb.** Nach dem Buchen von Hand blieben real 2 statt 7 Prüffälle und
5 Mails als „schon erfasst".

## ADR-051 – Betriebsfeiern sind keine Bewerbungstermine

**Problem.** Der Mailcheck meldete am 07.11.2026 eine „Einladungen / Zusagen (1
neu)" — es war die Einladung zur **Limonadenfeier** des aktuellen Arbeitgebers
(IGEL, BMW Welt). Ursache: `art_of` prüft `_EINLADUNG` ohne Bewerbungskontext,
und das Muster `laden (?:wir )?(?:sie|dich) … ein` trifft „Wir Laden Dich zu der
Limonadenfeier ein". Zugeordnet wurde daraufhin „6 offene Bewerbungen bei der
Firma, Titel nicht eindeutig". Der bereits vorhandene Schutz griff nur bei
„Zusage" (`_ANGEBOT_SCHWACH` mit `_APPKONTEXT`), nicht bei der Einladung.

**Entscheidung.** `_VERANSTALTUNG` (Weihnachts-/Limonaden-/Firmenfeier,
Sommerfest, Betriebsausflug, Team-Event, Save-the-Date, Dresscode, Glühwein,
Kick-off) schaltet `art_of` auf `""` — **außer** die Mail nennt ausdrücklich
„Vorstellungs-/Bewerbungsgespräch" oder „Interview". Damit bleibt eine echte
Einladung, die ein Teamevent erwähnt, eine Einladung.

**Grenze.** Die Liste ist an echten Formulierungen gebaut, kein NLP. Kommt eine
neue Feierformulierung durch, gehört sie hierher — nicht in `_APPKONTEXT`, denn
der bewirkt das Gegenteil (mehr Treffer).

**Nebenbei.** `tests/test_followup.py::test_nicht_faellige_zeile` prüfte mit
einem festen `sentAt="2026-10-24"` und wurde am 07.11.2026 ohne Codeänderung
rot (Frist abgelaufen). Datum jetzt relativ zu `date.today()`.

## ADR-050 – Anzeigentexte sind Pflicht, StepStone läuft über den Browser

Ausgangslage (06./07.11.2026): Seit dem 30.10. kamen **alle** neuen Stellen ohne
Anzeigentext an — StepStone und Arbeitnow liefern keinen mehr, die ATS-Boards
nur teilweise. Der Score rechnet Titel ×6 + Text ×4 + Wort ×2; ohne Text blieb
nur der Titel. Ergebnis: 0 von 185 textlosen Stellen über 65 %, während 42 von
542 mit Text die Schwelle erreichten. Eine Woche ohne neue Dashboard-Treffer war
die Folge — kein Stellenmangel, ein Pipeline-Loch.

**Entscheidungen.**

1. **`fetch` gehört in den Tageslauf**: `search → fetch (--limit 300) → match →
   enrich → dashboard`. Vorher lief `fetch` nur von Hand.
2. **`agent.py fetch --limit/--only-unsure`**, damit der Lauf begrenzbar ist.
3. **StepStone über den Browser** (`stepstone_browser`): Der HTTP-Provider
   bekommt seit Ende Oktober oft eine leere 200-Antwort (Bot-Abwehr), im Browser
   lädt die Liste normal (48 Treffer „Testingenieur" München, 25 Karten/Seite).
   Der Provider holt nur Titel/Firma/Ort/URL; den Text lädt anschließend
   `fetch` im selben Verfahren.
4. **`base.fetch` mit curl-Fallback**, wenn `requests` in den ReadTimeout läuft.
5. **Arbeitnow auf eine Seite begrenzt** (`arbeitnow_pages: 1`): 337 der 512
   neuen Einträge stammten von dort, überwiegend englische Nicht-Automotive-Jobs.
   `glassdoor` aus der Provider-Liste entfernt (nie implementiert, meldete bei
   jedem Lauf „Unbekannter Provider").

**Folgen.** Nach dem Nachladen von 40 Anzeigen: 542 mit Text → 42 ≥ 65 %,
185 ohne Text → 0. Bestand im Dashboard 219 Zeilen, 6 offene ≥ 65 %.

## ADR-052 – Quellen-Wiederaktivierung und Playwright-Selbstheilung

Ausgangslage (07.11.2026): XING, Indeed und `stepstone_browser` waren
abgeschaltet, ohne dass die Seiten blockierten. Ursachen: ein kurzer Netzausfall
(`ERR_INTERNET_DISCONNECTED`) und ein Playwright-Update, dessen Browser-Binärdatei
fehlte (`Executable doesn't exist`). Nach 3 Fehlläufen blieb eine Quelle für
immer aus; ohne XING/Indeed fielen rund zwei Drittel der brauchbaren Treffer weg.

**Entscheidungen.**

1. **`provider_health.release_due`**: Eine abgeschaltete Quelle wird nach
   `search.provider_health.retry_hours` (Standard 24, `0` = aus) einmal probeweise
   zugelassen. Der Fehlerzähler bleibt, ein weiterer Fehlschlag schaltet sofort
   wieder ab, ein Erfolg reaktiviert.
2. **`search/browser._launch`**: Meldet Chromium „Executable doesn't exist“, läuft
   einmal pro Prozess `python -m playwright install chromium`, danach ein
   zweiter Startversuch. Abschaltbar mit `BEWERBUNGSAGENT_NO_AUTOINSTALL=1`.
3. **JobLeads** liegt hinter einer Cloudflare-Abfrage (`Cf-Mitigated: challenge`)
   und ist aus der Provider-Liste genommen; die Bot-Abwehr wird nicht umgangen.
   JobLeads-Mails laufen weiter über den Mail-Import.

## ADR-053 – Review 07.11.2026: Mengenlauf nur für offene Einträge, Limits je Begriff

**Ausgangslage.** Ein Mengenlauf überschrieb am 07.11.2026 drei bestehende Ordner,
darunter den einer versendeten Bewerbung. `run_generate` las `matches.json`; dort
stehen auch Treffer, die `_merge_state` als Dublette einer anderen Börse verwirft.
Außerdem endeten die Browser-Suchen meist beim ersten Begriff, weil `max_results`
alle Begriffe zusammen begrenzte. `agent.py search` und der Tageslauf übergingen
Suchen mit `"daily": true`, und `agent.py pipeline` ließ `run_enrich` aus.

**Entscheidungen.**

1. **`run_generate` prüft den Bestand.** Der Mengenlauf überspringt Treffer ohne
   eigenen Eintrag sowie gelöschte und abgeschlossene Stellen. `--ids` bleibt ein
   ausdrücklicher Wunsch. `run_enrich` schließt abgeschlossene Stellen ebenso aus.
2. **Ein Fehler betrifft nur seine Stelle.** `_generate_sicher` sammelt Fehler in
   `failed`. Das Wochenbudget zählt nur erfolgreich erzeugte Unterlagen.
3. **`max_results` gilt je Begriff** bei `stepstone_browser`, `xing` und `indeed`.
4. **Bekannte Texte werden nicht neu geladen.** `known_urls` kommt aus dem Bestand
   und spart Detailabrufe; `_preserve_descriptions` spielt den Text zurück.
5. **Arbeitnow liefert den Volltext**, begrenzt auf 20.000 Zeichen. Workday filtert
   über die Facette `locationCountry` (Board-Feld `country`, Standard `Germany`)
   und lädt Texte über den JSON-Detail-Endpunkt.
6. **`run_search` ohne Definition führt alle Tagessuchen aus**, `run_full` enthält
   `run_enrich`.
7. **Statistikzeilen sind keine Fehler.** `ats.is_info` trennt sie; sie stehen in
   `hinweise` statt in `fehler`.

**Folgen.** Scores bleiben unverändert (Alt-Neu-Vergleich auf 11.314 echten
Texten: 0 Abweichungen). Mehr Begriffe bedeuten mehr Browserzeit; nach dem ersten
Lauf entfällt der Textabruf für bekannte Anzeigen. Die Board-Einstellungen in der
`config.json` brauchen keine Änderung. Gespeicherte Suchen mit dem Provider
`stepstone` sollten auf `stepstone_browser` wechseln.

## ADR-054 – Stellen, die fehlen, und Quellen, die ausfallen, werden sichtbar

**Ausgangslage.** Am 07.11.2026 tauchten 22 von 60 offenen Einträgen im Suchlauf
nicht mehr auf, der Bestand merkte sich das aber nicht. `verfuegbar` wird nur beim
ersten Nachladen gesetzt. Ausfälle einzelner Boards standen nur im Digest, wenn
der Bestand schrumpfte, und das kann er seit dem Wechsel auf die Datenbank nicht
mehr durch einen Ausfall. Das Log-Parsing nannte außerdem `Standard` statt der
Quelle, weil `run_searches` die Zeilen mit dem Suchnamen beginnt. NXP meldete nur
`JSONDecodeError`, der Workday-Host `wd3` stand fest im Code.

**Entscheidungen.**

1. **`zuletzt_gesehen` kommt von der Suche.** `run_search` und `run_searches`
   stempeln `jobs.json`, `_merge_state` übernimmt den Wert. So frischt ein `match`
   ohne neue Suche nichts auf. Findet eine andere Börse dieselbe Stelle, rückt der
   Zeitpunkt beim bestehenden Eintrag trotzdem vor. Versendete Stellen bekommen das
   Feld auch; Status und Bewertung bleiben nach ADR-039 eingefroren.
2. **Vermisst heißt: Die Quelle lief, die Stelle fehlte.** „Vermutlich abgelaufen"
   vergleicht `zuletzt_gesehen` mit dem letzten Erfolg der eigenen Quelle
   (`provider_health.letzter_abruf`), nicht mit dem heutigen Datum. Ein Ausfall,
   eine abgeschaltete Quelle oder ein pausierter Tageslauf macht keine Stelle
   verdächtig. Es gilt nur für offene Stellen, wird beim Anzeigen berechnet und
   löscht nichts. Frist: `search.abgelaufen_nach_tagen`, Standard 7, `0` = aus.
3. **Altbestand beginnt beim ersten Lauf.** Offene Einträge ohne Feld, die dieser
   Lauf nicht findet, erhalten den aktuellen Zeitpunkt. Seit wann sie fehlen, ist
   unbekannt; `created` würde am ersten Tag fast alles markieren. Die 22 Einträge
   erscheinen deshalb erst nach Ablauf der Frist.
4. **Boards führen eine eigene Historie (`board_health`)** mit `provider_health.record`,
   werden aber nie abgeschaltet (`max_failures=None`).
5. **`ats.search` trennt Fehler und Statistik.** Die Fehlerliste enthält nur noch
   echte Fehler, die Statistik steht im Ausgabeparameter `status`. Das ersetzt
   `ats.is_info` aus ADR-053, Nr. 7. Alle Boards laufen über `_abfragen` mit einer
   einzigen Fehlerbehandlung.
6. **Der Digest liest die Historie, nicht das Log.** `parse_failed_sources` entfällt.
   `stoerungen` und `aenderungen_seit` melden neue Ausfälle, Abschaltungen und
   Erholungen je Änderung einmal, in einem eigenen Block `Quellen:`. Als gemeldet
   gilt nur, was zugestellt wurde (`gemeldete_quellen` im Snapshot): Ein gescheiterter
   Versand oder `--dry-run` holt die Meldung nach. Die Probe aus `release_due` bleibt
   still, die Quelle ist weiter gestört.
7. **Workday-Host je Board.** Feld `host`: Instanz (`wd5`) oder ganzer Hostname,
   Standard `wd3`. Antwortet ein JSON-Board mit HTML, nennt `BoardAntwortFehler`
   Seitentitel und Host statt `JSONDecodeError`; `_fehlertext` nennt bei HTTP-Fehlern
   den Status.

**Live geprüft (07.11.2026).** Airbus liefert auf `wd3` JSON und auf `wd1`/`wd5`
HTTP 422, also ist 422 das Zeichen für einen falschen Host. NXP liefert auf `wd3`
per 303 die Seite „Workday is currently unavailable." von `community.workday.com`,
auf `wd1`, `wd5`, `wd10`, `wd12`, `wd103` und `wd105` HTTP 422, auf `wd2` und `wd101`
keine Verbindung. Das spricht gegen einen falschen Host; ein anderer Wert behebt NXP
also vermutlich nicht. Der Standard `wd3` bleibt.

**Grenzen.** Die Frist von 7 Tagen ist gesetzt, nicht gemessen: Für eine Kalibrierung
fehlt die Historie (Hard Rule 3). Börsen liefern nur die ersten Treffer je Begriff,
eine Anzeige kann also herausrutschen und trotzdem online sein. Deshalb „vermutlich".
Ein Board, das fehlerfrei 0 Stellen liefert, gilt nicht als Ausfall; seine Stellen
gelten nach der Frist als vermutlich abgelaufen. `quelle` nennt die erste Fundstelle.

**Folgen.** `board_health` ist ein neuer Meta-Schlüssel, ein Schema-Umbau entfällt.
Beim ersten Digest erscheinen bestehende Störungen einmal als neu, auch solche von
Quellen, die nicht mehr konfiguriert sind.

## ADR-056 – Eine Schrittliste für alle Laufwege, Löschgrund als Feld

**Ausgangslage.** Vier Laufwege führten eigene Schrittfolgen. `run_full` ließ `fetch`
aus und bewertete neue Stellen nur nach dem Titel (ADR-050), `jobwatch` kannte weder
`generate` noch `quality`, und der Graph brach bei einem Fehler im Nachladen ab. Die
Review vom 07.11.2026 führte mehrere Fehler auf diese Abweichungen zurück (ADR-053).
Unabhängig davon entschied `run_enrich` über Textanfänge von `deleted_reason`. Eine
umformulierte Begründung hätte die Neubewertung still geändert, und
„Fit <= 60 Prozent (Nutzerkriterium)" beginnt mit demselben Wort wie die
automatische Fit-Ausblendung.

**Entscheidungen.**

1. **`bewerbungsagent/schritte.py` hält die Folge:** `search`, `fetch`, `match`,
   `enrich`, `generate`, `quality`, `dashboard`. Der Name ist zugleich Unterbefehl
   von `agent.py`, Knoten im Graphen und Schlüssel im Ergebnis. Die Graphknoten
   heißen deshalb nicht mehr `suche`, `beschreibung` und `qualitaet`.
2. **`fetch` gehört in `run_full`,** ebenso `quality`. Auch `agent.py pipeline`
   braucht Anzeigentexte, sonst bleibt der Fit beim Titel hängen. Das Limit von
   300 Anzeigen gilt jetzt in jedem Laufweg. Der Graph lädt in bis zu zwei
   Durchgängen, der Rest folgt im nächsten Lauf.
3. **`fetch` und `quality` dürfen scheitern.** `schritte.fuehre_aus` sammelt den
   Fehler, Pflichtschritte reichen ihn weiter. `jobwatch` wertet dasselbe Feld aus.
4. **Der Graph wird aus der Liste gebaut.** Eigene Knoten sind nur `triage` und
   `review`; beide tun keine Arbeit.
5. **`jobwatch` führt jetzt auch `generate` und `quality` aus.** Je Schritt bleibt es
   ein eigener Prozess, damit ein Browser-Absturz nicht den Digest trifft.
6. **Die Shell-Skripte haben keine eigene Liste.** `tageslauf.sh` und `wochenlauf.sh`
   waren bis auf den Namen gleich und rufen nun `scripts/lauf.sh`, das
   `agent.py ablauf` startet.
7. **`deleted_code` steuert die Logik, `deleted_reason` bleibt Anzeigetext.** Werte:
   `nutzer`, `kriterium`, `fit`, `pendel`, `research`, `student`, `techniker`,
   `sonstig`. Neu bewertet werden nur `fit`, `pendel` und `research`. Das Feld liegt
   in der `user`-Spalte. Den Text legt nur noch `db.delete_code_aus_text` aus, und
   zwar an den Rändern: beim Schreiben ohne Code und bei Dashboard-Eingaben, damit
   das Dashboard unverändert bleibt.
8. **Der Bestand zieht über `db.Store` um,** einmalig beim ersten Öffnen,
   festgehalten im Meta-Eintrag `migration_delete_code`. Alembic läuft nur beim
   Anlegen des Schemas, und das Feld liegt in einer JSON-Spalte. Bei jedem Öffnen
   Alembic zu laden wäre teuer, denn `Store` entsteht je Schritt neu.
9. **Der Umzug des Live-Ordners ist nicht entschieden.** Der Vorschlag steht in
   `docs/PLAN-LIVE-ORDNER.md`.

**Folgen.** Scoring und Fit-Bänder bleiben unverändert. Alte und neue Fassung von
`run_enrich` entschieden auf einer Kopie des Bestands gleich: 2.262 Einträge, zwei
Läufe nacheinander, 0 Abweichungen bei `deleted`, Grund, Status und allen Zählern.
Pendelweg und Dokumenterzeugung waren dabei ersetzt. Die Codes verteilten sich auf
1.468 `fit`, 331 `research`, 98 `pendel`, 56 `techniker`, 23 `student`, 20 `nutzer`,
16 `kriterium` und 4 `sonstig`. `eval/` liest weiter den Text, weil es Altdaten
auswertet. Ein laufender Dashboard-Server braucht nach dem Einspielen einen Neustart;
bis dahin erhält eine Löschung dort ihren Code erst beim nächsten Schreiben. Ohne
LangGraph scheitert `agent.py ablauf` und damit `lauf.sh` weiterhin mit klarer
Meldung, `agent.py pipeline` läuft auch ohne.


## ADR-057 – Live-Ordner wird Datenordner, Code kommt aus dem Repo

**Ausgangslage.** Code lag doppelt vor: im Repo und im Drive-Ordner `04_Agent`, aus
dem alle Läufe starten. Ein Fix in `fetch_descriptions.py` gab es nur dort,
`search/glassdoor.py` lag nur dort, und der Drive-Sync kann Änderungen zurückdrehen.
Der Vorschlag in `docs/PLAN-LIVE-ORDNER.md` stellte drei Varianten zur Wahl.

**Entscheidungen** (Nutzer, 08.11.2026).

1. **Variante A:** `04_Agent` behält Name und Ort und hält nur noch Daten
   (`config.json`, `data/`, `output/`, `eval/labels.csv`). Der Code läuft aus einem
   eigenen Release-Checkout, editierbar ins venv installiert.
2. **`AGENT_ROOT` heißt Datenordner** und kommt aus `BEWERBUNGSAGENT_HOME`, sonst wie
   bisher aus dem Ordner über dem Paket. Weil `04_Agent` bleibt, gelten die relativen
   Pfade der `config.json` und die 1.560 Dokumentpfade im Bestand weiter. Der Code-Ort
   heißt `CODE_ROOT`.
3. **Server, `jobwatch`, `lauf.sh` und `eval/` trennen Code und Daten.** Der Server
   sperrt den Datenordner auch unter seinem tatsächlichen Namen. `lauf.sh` nimmt die
   Code-Kopie im Datenordner, solange es sie gibt; der Wechsel geschieht beim Umzug
   von selbst.
4. **`pyproject.toml` nennt `agent`, `server` und `fetch_descriptions` als
   `py-modules`.** Eine editierbare Installation fand sie vorher nicht.
5. **`glassdoor.py` ist im Repo** und als Provider `glassdoor` angebunden. In der
   Standardliste steht er nicht; aktiv wird er erst über `search.providers`.
6. **Linux und der Raspberry Pi ziehen mit um.** Ihre Starter werden vor dem
   Entfernen der Code-Kopien umgestellt.

**Folgen.** Ohne `BEWERBUNGSAGENT_HOME` ändert sich nichts; die Änderungen lassen sich
vor dem Umzug einspielen. `tests/conftest.py` entfernt die Variable, damit die Suite
nie den echten Datenordner liest. Der Umzug selbst ist nicht ausgeführt; seine
Schritte und der Rückweg stehen in `docs/PLAN-LIVE-ORDNER.md`. Regel 6 aus
`AGENTS.md` (zwei Code-Orte) entfällt erst nach dem Umzug.

## ADR-058 – Wirkungslose Provider und widerlegte Experimente entfernt

**Ausgangslage.** Bing und DuckDuckGo lieferten live nichts Brauchbares, der
HTTP-Provider `stepstone` wird von StepStone mit leeren Antworten bedient und ist
durch `stepstone_browser` ersetzt (ADR-050). `semantic.py` und `rerank.py` schlugen
den Keyword-Fit nicht (ADR-015, ADR-016) und liefen nur noch in `eval/`.

**Entscheidung.** Die drei Provider, beide Module, ihre Auswertungen und das Extra
`semantic` sind entfernt. Die Git-Historie bewahrt sie. Der Name `stepstone` in einer
Konfiguration meldet jetzt „Unbekannter Provider“. Die Messergebnisse bleiben in den
ADRs und im README stehen.

## ADR-052 – Firmen- und Titelmatch: nur kennzeichnende Wörter, spezifischster Titel gewinnt

**Problem.** Am 10.11.2026 blieb die **Interview-Einladung** von SII Consulting
(vorgeschlagener Termin: Mo 09.11. 15:30, Webex) unzugeordnet — der Mailcheck
meldete nur „4 offene Bewerbungen passen zum Titel". Zwei Ursachen:

1. `firma_passt` verglich den ersten Firmen-Token als **Teilzeichenkette** mit der
   Absender-Domain. „MAN Truck & Bus" (Token `man`) traf damit `sii-germany.com`
   (`…ger`**`man`**`y…`), „Software Engineering GmbH" (Token `software`) traf jeden
   Anzeigentext. Aus 3 wurden 18 Kandidaten.
2. Bei mehreren Titel-Treffern brach `match_mail` ab. Eine Consultancy schreibt
   aber mehrere Rollen derselben Gattung aus: „Test Engineer", „Software Test
   Engineer" und „Software Test Engineer Verteidigungsindustrie" passen alle auf
   denselben Mailtext.

**Entscheidung.**

1. Domain wird in **Segmente** zerlegt (`[^a-z0-9]+`) und Token gegen Segment
   geprüft (`gleich` oder `startswith` ab 4 Zeichen) — kein Teilwort mehr.
2. Für den Text-Fallback (`Firma steht im Betreff/Body`) zählen nur
   kennzeichnende Tokens; `_FIRMA_GENERISCH` (software, hardware, system, test,
   data, man, engineering, consulting, …) belegt ohne Domain-Treffer nichts.
3. Passen mehrere Titel, gewinnt der **spezifischste**: meiste kennzeichnende
   Wörter im Kerntitel (`_kern_worte`, ohne Gender-Tag und Generika). Nur bei
   Gleichstand bleibt es unklar — dann ist Raten weiter verboten.

**Grenze.** Der Tie-Break ordnet zu, er prüft nicht inhaltlich. Zwei Anzeigen mit
gleich langem, verschiedenem Titel bleiben „unklar" und müssen vom Nutzer
entschieden werden.

## ADR-059 – Review 11.11.2026: Verschlankung

**Kontext.** Der Agent war auf rund 21.000 Zeilen gewachsen. Mehrere Teile liefen nur
noch berichtend, wurden nie genutzt oder hatten keinen Nutzen mehr.

**Entscheidungen** (Sparring mit Jacob am 11.11.2026):

1. **Ein Laufweg.** Nur noch `scripts/jobwatch.py` (Hermes). Entfernt: LangGraph-Ablauf
   (`orchestrator.py`, `agent.py ablauf`), `run_full`/`agent.py pipeline`, die Pi-Skripte.
2. **Lebenslauf:** DOCX-Vorlage plus Ersatzdesign `classic`. Sechs weitere Designs und
   das nie genutzte Tailoring entfernt. LibreOffice wird unter Windows am
   Installationsort gefunden; vorher entstand still jeder Lebenslauf im Ersatzdesign.
3. Englische Unterlagen bleiben und werden immer mit erzeugt.
4. **Mehrdimensionale Bewertung** samt K.O.-Liste entfernt (war seit ADR-031 nur berichtend).
5. **Einordnung nach drei Regeln** (`pipeline._einordnung`):
   Pendelweg über der Grenze → Research bis Grenze + Kulanz und ab 65 %, sonst
   ausgeblendet; Fit unter 65 % → ausgeblendet (außer angeforderte Unterlagen);
   sonst sichtbar, bis 70 % Research, ab 71 % Unterlagen. Research-Filter und
   Prüffall „Text fehlt“ entfallen; Stellen ohne Text bleiben ausgeblendet, bis der
   Lauf den Text nachgeladen hat.
6. **Quellen:** JobLeads (ohne Abo kein Weg zur Ausschreibung), Labo (0 relevante
   Funde) und der Glassdoor-Provider entfernt. Arbeitnow bleibt vorerst.
7. **Titelregeln:** Der Domänen-Vorfilter (vormals `triage.py`) liegt in `matching.py`.
   Er bleibt breiter als `has_role_signal`: 58 von 230 Bewerbungen hatten kein
   Rollensignal im Titel.
9. Einmal-Skripte, Alt-Dashboard-Import und Pi-Backups entfernt.
10. Überholte ADRs liegen in `docs/archiv/DECISIONS-ARCHIV.md`.

Punkt 8 (Dashboard) folgt in einem eigenen Sparring.

