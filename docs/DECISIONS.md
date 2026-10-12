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
