"""Tests für die Evaluations-Metriken (``eval/metrics.py``) und Labels."""

from __future__ import annotations

import pytest

from eval import labels as L
from eval import metrics as M


class TestConfusionMatrix:
    def test_perfect_prediction(self):
        c = M.confusion_matrix([True, False, True], [True, False, True])
        assert (c.tp, c.fp, c.fn, c.tn) == (2, 0, 0, 1)

    def test_all_wrong(self):
        c = M.confusion_matrix([True, True], [False, False])
        assert (c.tp, c.fp, c.fn, c.tn) == (0, 0, 2, 0)

    def test_all_positive_prediction(self):
        c = M.confusion_matrix([True, False], [True, True])
        assert (c.tp, c.fp, c.fn, c.tn) == (1, 1, 0, 0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            M.confusion_matrix([True], [True, False])

    def test_empty(self):
        c = M.confusion_matrix([], [])
        assert c.total == 0
        assert M.precision(c) == 0.0
        assert M.recall(c) == 0.0
        assert M.f1(c) == 0.0


class TestMetrics:
    def test_precision_recall_f1_known_case(self):
        # tp=3, fp=1, fn=2  -> P=0.75, R=0.60, F1=0.6667
        c = M.Counts(tp=3, fp=1, fn=2, tn=4)
        assert M.precision(c) == pytest.approx(0.75)
        assert M.recall(c) == pytest.approx(0.60)
        assert M.f1(c) == pytest.approx(24 / 36, abs=1e-6)

    def test_no_positive_predictions_does_not_crash(self):
        c = M.Counts(tp=0, fp=0, fn=5, tn=5)
        assert M.precision(c) == 0.0
        assert M.recall(c) == 0.0
        assert M.f1(c) == 0.0

    def test_accuracy_and_balanced_accuracy(self):
        # Imbalance-Beispiel: alles negativ vorhergesagt
        c = M.Counts(tp=0, fp=0, fn=2, tn=8)
        assert M.accuracy(c) == pytest.approx(0.8)
        assert M.recall(c) == 0.0
        assert M.specificity(c) == 1.0
        assert M.balanced_accuracy(c) == pytest.approx(0.5)

    def test_perfect_scores(self):
        c = M.Counts(tp=5, fp=0, fn=0, tn=5)
        assert M.precision(c) == 1.0
        assert M.recall(c) == 1.0
        assert M.f1(c) == 1.0
        assert M.accuracy(c) == 1.0
        assert M.balanced_accuracy(c) == 1.0


class TestEvaluationAtThreshold:
    def test_threshold_separates_correctly(self):
        labeled = [(90.0, True), (80.0, True), (30.0, False), (20.0, False)]
        c = M.evaluate_at(labeled, 60.0)
        assert (c.tp, c.fp, c.fn, c.tn) == (2, 0, 0, 2)

    def test_threshold_zero_predicts_all_positive(self):
        labeled = [(10.0, True), (0.0, False)]
        c = M.evaluate_at(labeled, 0.0)
        assert c.fn == 0
        assert c.fp == 1

    def test_threshold_above_all_predicts_all_negative(self):
        labeled = [(10.0, True), (99.0, False)]
        c = M.evaluate_at(labeled, 100.0)
        assert c.tp == 0
        assert c.fn == 1


class TestSweepAndBaseline:
    def test_best_by_f1_prefers_balanced_threshold(self):
        labeled = [(95.0, True), (85.0, True), (75.0, False), (65.0, False)]
        sweep = M.threshold_sweep(labeled, thresholds=[60.0, 90.0])
        best_t, best_c = M.best_by_f1(sweep)
        # Bei 90: tp=1, fn=1 -> F1=0.667 ; bei 60: tp=2, fp=2 -> F1=0.667
        assert best_t in (60.0, 90.0)
        assert M.f1(best_c) > 0

    def test_majority_baseline_predicts_majority_class(self):
        # 1 positiv, 3 negativ -> Baseline sagt immer negativ
        labeled = [(90.0, True), (10.0, False), (20.0, False), (30.0, False)]
        c = M.majority_baseline(labeled)
        assert c.tp == 0
        assert c.fn == 1
        assert c.tn == 3
        assert M.accuracy(c) == pytest.approx(0.75)

    def test_sweep_covers_range(self):
        labeled = [(50.0, True)]
        sweep = M.threshold_sweep(labeled)
        assert len(sweep) == 21  # 0..100 in 5er-Schritten
        assert sweep[0][0] == 0.0
        assert sweep[-1][0] == 100.0


class TestLabels:
    def _apps(self):
        return [
            {"firma": "A", "titel": "T1", "status": "sent", "sentAt": "2026-09-09",
             "score": 80, "beschreibung": "x"},
            # Prozess-Status: beworben -> KEIN Fit-Label (ADR-012)
            {"firma": "B", "titel": "T2", "status": "rejected", "score": 70},
            # Explizites Eignungsurteil (inhaltlich) -> negativ
            {"firma": "C", "titel": "T3", "status": "research", "score": 75,
             "deleted": True, "deleted_reason": L.EXPLICIT_NEGATIVE_REASON},
            # Score-basiert -> zirkulär, kein Label
            {"firma": "D", "titel": "T4", "status": "research", "score": 30,
             "deleted": True, "deleted_reason": "Fit <= 60 Prozent (Nutzerkriterium)"},
        ]

    def test_status_is_not_used_as_fit_label(self):
        """Kernkorrektur: 'sent'/'rejected' dürfen keine Fit-Labels erzeugen."""
        ds = L.build_dataset(self._apps())
        sources = {e.source for e in ds}
        assert sources == {"explicit_reject"}
        assert all(e.firma != "A" for e in ds)  # sent ist kein Fit-Label
        assert all(e.firma != "B" for e in ds)  # rejected ebenso wenig

    def test_explicit_reject_is_negative(self):
        ds = L.build_dataset(self._apps())
        c = next(e for e in ds if e.firma == "C")
        assert c.label is False

    def test_manual_labels_override(self):
        apps = self._apps()
        key = L.entry_key(next(a for a in apps if a["firma"] == "A"))
        ds = L.build_dataset(apps, {key: True})
        manual = next(e for e in ds if e.firma == "A")
        assert manual.source == "manual"
        assert manual.label is True

    def test_circular_delete_detected(self):
        apps = self._apps()
        d = next(a for a in apps if a["firma"] == "D")
        assert L.is_circular(d) is True
        c = next(a for a in apps if a["firma"] == "C")
        assert L.is_circular(c) is False

    def test_fit_value_prefers_fit_pct(self):
        assert L.fit_value({"fit_pct": 77, "score": 20}) == 77.0
        assert L.fit_value({"score": 55}) == 55.0
        assert L.fit_value({}) == 0.0

    def test_diagnostics_keys_and_counts(self):
        d = L.diagnostics(self._apps())
        assert d["total_apps"] == 4
        assert d["explicit_reject_negatives"] == 1
        assert d["circular_deletes_excluded"] == 1
        assert d["applied_but_not_a_fit_label"] == 1  # nur A hat sentAt
        assert d["dataset_size"] == 1

    def test_manual_labels_roundtrip(self, tmp_path):
        p = tmp_path / "labels.csv"
        L.append_manual_label("k1", True, p)
        L.append_manual_label("k2", False, p)
        got = L.load_manual_labels(p)
        assert got == {"k1": True, "k2": False}

    def test_load_manual_labels_missing_file(self, tmp_path):
        assert L.load_manual_labels(tmp_path / "nope.csv") == {}


class TestLabelTool:


    def _apps(self):
        return [
            {"firma": "A", "titel": "Techniker", "score": 80, "beschreibung": "CAN HiL"},
            {"firma": "B", "titel": "Buchhalter", "score": 75, "beschreibung": "FiBu"},
            {"firma": "C", "titel": "Ohne Text", "score": 50, "beschreibung": ""},
            {"firma": "D", "titel": "Dupe", "score": 60, "beschreibung": "x",
             "deleted_reason": "Duplikat (Firma+Titel bereits vorhanden)"},
            {"firma": "E", "titel": "Fremd", "score": 40, "beschreibung": "y",
             "deleted_reason": L.EXPLICIT_NEGATIVE_REASON},
        ]

    def test_candidates_exclude_undesirable(self):
        from eval.label_tool import candidates
        got = candidates(self._apps(), skip_keys=set(), require_description=True)
        namen = {a["firma"] for a in got}
        assert namen == {"A", "B"}  # C ohne Text, D Duplikat, E bereits negativ

    def test_candidates_skip_known(self):
        from eval.label_tool import candidates
        apps = self._apps()
        got = candidates(apps, skip_keys={L.entry_key(apps[0])})
        assert "A" not in {a["firma"] for a in got}

    def test_classify_input(self):
        from eval.label_tool import classify_input
        assert classify_input("j") == (True, "passt")
        assert classify_input("N") == (False, "passt nicht")
        assert classify_input("s") == (None, "unsicher")
        assert classify_input("q") == (None, "quit")
        assert classify_input("quatsch") == (None, "unbekannt")

    def test_stratify_covers_all_bands(self):
        from eval.label_tool import stratify_by_fit
        apps = [{"firma": str(i), "titel": "t", "score": s}
                for i, s in enumerate([5, 25, 55, 85, 10, 60, 90])]
        got = stratify_by_fit(apps, bands=4)
        assert len(got) == len(apps)  # nichts verloren/dupliziert

    def test_run_session_writes_labels(self, tmp_path):
        from eval.label_tool import run_session
        answers = iter(["j", "n"])
        p = tmp_path / "labels.csv"
        stats = run_session(self._apps(), p, limit=2, desc_chars=50,
                            input_fn=lambda _="": next(answers),
                            print_fn=lambda *a, **k: None)
        assert stats["labeled"] == 2
        assert stats["positive"] == 1
        assert stats["negative"] == 1
        saved = L.load_manual_labels(p)
        assert len(saved) == 2

    def test_run_session_quit_stops(self, tmp_path):
        from eval.label_tool import run_session
        p = tmp_path / "labels.csv"
        stats = run_session(self._apps(), p, limit=5, desc_chars=50,
                            input_fn=lambda _="": "q",
                            print_fn=lambda *a, **k: None)
        assert stats["labeled"] == 0
        assert not p.exists() or L.load_manual_labels(p) == {}

