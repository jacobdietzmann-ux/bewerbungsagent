# Projekt-Gedächtnis (kuratiert)

Verdichtetes Wissen aus der Entwicklungssitzung. Ersetzt **nicht** das
Roh-Transkript (siehe `BACKUP.md`), sondern hält die Erkenntnisse fest, die
man später wirklich braucht.

## Was gebaut wurde

Ein lokaler Bewerbungsagent mit vier Stufen (Suche → Matching → Dokumente →
Dashboard) plus einem Weboberfläche-Server für Live-Statusänderungen.

## Gelernte Lektionen (aus echten Fehlern)

1. **Silent-Fail durch Fallback-Werte.** `_fmt_date` fiel auf „heute" zurück.
   Ergebnis: eine plausible, aber falsche Statistik. *Lehre:* Fallbacks
   sichtbar machen und mit Tests absichern.
2. **String-Normalisierung ist eine Falle.** `strip("()")` vor einem
   Regex-Split zerstörte das Muster. *Lehre:* Reihenfolge von
   Normalisierung/Split explizit testen.
3. **Kontext-spezifische Generika.** Das Wort „Analyse" entstand als
   eigenständiges Keyword, weil ein Skill-String Kommas enthielt.
   *Lehre:* Noise-Listen + Tests gegen generische Tokens.
4. **Sync vs. Arbeitsverzeichnis.** Ein Cloud-Sync (rclone-bisync) kann
   lokale Änderungen zurücksetzen. *Lehre:* Repos/VCS niemals auf
   Sync-Mounts betreiben.
5. **Caches brauchen Invalidierung.** Der Dashboard-Server cached HTML.
   Ohne Invalidierung bei Template-Änderung zeigt er Altstand.
   *Lehre:* Cache-Key = alle Eingaben (State *und* Code).
6. **Encoding-Realität.** PDF-Standardschriften sind Latin-1. Unicode-Pfeile
   wurden zu „■"-Boxen. *Lehre:* Sanitizing-Layer vor dem Rendern.
7. **Mehrsprachigkeit ist mehr als Überschriften.** Deutsche Skill-Labels
   blieben in englischen Dokumenten. *Lehre:* Alle Ausgabepfade prüfen, nicht
   nur die offensichtlichen.
8. **Verifizieren statt vertrauen.** Ein Mutationstest (Bug absichtlich
   wieder einbauen) beweist, dass Tests wirklich greifen.

## Wiederkehrende Arbeitsmuster

- **Backup vor destruktiven Schritten** (`state.backup.pre-*.json`).
- **History-Schutz**: versendete Bewerbungen nie überschreiben.
- **Kleine, verifizierte Schritte** statt großer Umbauten.
- **Headless-Browser** für JS-gerenderte Seiten (StepStone blockt `requests`).

## Offene Punkte / Ideen

- [ ] Metriken: Fit-Präzision gegen manuelle Bewertung messen (Evaluation).
- [ ] Suche um weitere Provider erweitern.
- [ ] Coverage-Report in CI (`pytest --cov`).
- [ ] Interessenkonflikte: Welche Skills fehlen im Profil, tauchen aber
      häufig in Top-Jobs auf? (Gap-Analyse)

## Session-Erkenntnisse: Labels & Evaluation (12.10.2026)

**Der teuerste Fehler war eine falsche Label-Definition.** `rejected` wurde
als „schlechter Fit" interpretiert. Tatsächlich heißt es „Bewerbung versendet,
von der Firma abgelehnt". Der Nutzer stellte klar:

> „Der Status der Stellen hat keinen Zusammenhang mit meiner Eignung zu der
> Stelle. Das ist nur der Status während des Bewerbungsprozesses."

Folge: 115 von 138 vermeintlichen „Negativ"-Labels waren in Wahrheit positive
Beispiele. Alle abgeleiteten Zahlen waren wertlos.

**Zweiter Fehler: Zirkularität.** Labels, die aus dem Modell-Score abgeleitet
werden („Fit ≤ 60 % → passt nicht"), erzeugen zwangsläufig perfekte Metriken
(P=R=F1=100 %) — und null Information. Solche Fälle müssen erkannt und
ausgeschlossen werden.

**Dritter Fehler: der Nutzer stimmte dem Score zu.** Auf „alle FIT sind
realistisch" folgte die Einsicht: Zustimmung liefert keine Information, nur
*Widerspruch* tut es (Prinzip des Active Learning). Wertvoll sind Labels, wo
die Einschätzung des Menschen vom Modell abweicht.

**Ergebnis der ersten echten Messung (8 Labels):** Der Keyword-Fit trennt die
Klassen nicht — unpassende Stellen scoren im Mittel höher (50 % vs. 44 %).
Keyword-Überlappung misst Vokabular, nicht Relevanz. Das ist die empirische
Begründung für Semantic Search.

**Methodische Lehren:**
1. Label-Semantik gehört in die Spezifikation, nicht in eine Fußnote.
2. Accuracy ist bei Klassen-Ungleichgewicht wertlos (Baseline: 98 % Accuracy
   bei Recall 0).
3. Zustimmung zum Modell ≈ kein Label; Widerspruch = Information.
4. Kleine Stichproben sind trotzdem nützlich, wenn der Effekt groß ist.


## Session-Erkenntnisse: Embeddings & Cross-Encoder (12.10.2026)

**Beide Hypothesen wurden widerlegt — mit Nutzen.**

Getestet wurden zwei komplexe Alternativen zum Keyword-Matching:

| Verfahren | AUC (harte Fälle) | Kosten |
|---|---:|---|
| **Keyword-Fit** | **0.715** | ~0 ms |
| Bi-Encoder (e5) | 0.560 | vorberechenbar |
| Cross-Encoder (bge) | 0.460 | ~150 ms/Stelle |

Der Keyword-Matcher gewinnt — auf einem Datensatz, auf dem er angeblich
scheitert („Head of Finance Systems" mit 75 %). Die empirische Prüfung hat
verhindert, zwei langsamere und schlechtere Verfahren einzubauen.

**Drei Instanzen desselben Fehlertyps (Silent Bug durch ungeprüfte Annahme):**

1. E5 schneidet bei 512 Token ab → 1484-Token-Profil wurde still beschnitten.
   Fix hob die AUC von 0.776 auf 0.924.
2. Cross-Encoder hat 512 Token für Anfrage UND Dokument gemeinsam → bei
   295-Token-Anfrage blieben der Stelle nur 217 Token.
3. `write_text` fehlte im Code, während das Skript „Report geschrieben"
   ausgab → die Datei existierte nie; zweimal hintereinander.

**Lehre:** Randbedingungen (Token-Limits, Datei-Schreibvorgänge) müssen
*verifiziert*, nicht *angenommen* werden. Die Ausgabe „es hat funktioniert"
ist kein Beweis.

**Der teuerste Einzelfehler:** Eine Konfiguration auf **4 handgeprüften
Beispielen** optimiert (AUC 0.730) — auf 20 echten Labels war sie schlechter
als die Alternative (0.460). Klassisches Overfitting an einer Mini-Stichprobe.
Genau dagegen existiert das Label-Set.

**Erfolgsfaktor:** Ohne die Baseline aus Schritt 1 wären beide Fehlansätze
eingebaut worden. Die Evaluation hat nicht die Lösung geliefert, sondern die
**Fehlentscheidungen verhindert** — das ist der eigentliche Wert.


## Session: Best-Practice-Verbesserungen (12.10.2026, nachmittags)

Vier Verbesserungen umgesetzt — und dabei zwei weitere Instanzen des
bekannten Fehlertyps („Annahme nicht verifiziert") gefunden:

1. **Schwellenwert-Kalibrierung** (Decision Theory): Der „beste" Schwellenwert
   ist keine feste Zahl, sondern hängt vom Geschäftsziel ab (max. Recall bei
   Precision ≥ X vs. max. Precision bei Recall ≥ Y). Der Report zeigt jetzt
   beides + wie viele Labels für ein belastbares CI nötig sind (~53/Klasse
   statt der vorhandenen 10/10).

2. **Sample-Size-Bug:** `required_sample_size` lieferte den Multiplikator
   (z·se/target)² statt der absoluten Zahl. Erst ein Plausibilitätscheck
   (CI ±23 pp, aber „5 Labels reichen"?) deckte es auf. Richtig:
   n_min × Multiplikator. → Ein Ergebnis auf Plausibilität prüfen, nicht nur
   auf korrekte Formel.

3. **Linting (ruff):** 66 Fehler — unbenutzte Imports/Variablen, doppelte
   Set-Einträge, zip() ohne strict, Semikolons. Die erste Konfiguration war
   zu breit (E501/RUF001-003 erzeugten 100+ Rauschen durch deutsche Umlaute
   und lange Docstrings) — Konfiguration nachgeschärft.

4. **Golden-File-Tests:** Die Text-Bausteine der PDF-Erzeugung getestet
   (headline, sanitize, esc, summary_skills, intro). Dabei ein echter Bug:
   das öffnende „ (U+201E) fehlte in der sanitize-Tabelle und blieb in PDFs.

**Lehre:** Der Wert von Linting/Coverage liegt nicht im „grünen Häkchen",
sondern darin, dass sie genau die Fehlerklasse finden, die man *nicht*
vermutet. Dreimal in dieser Session wurde ein Ergebnis geglaubt, das falsch
war — und nur ein Plausibilitätscheck bzw. ein Test hat es entdeckt.
