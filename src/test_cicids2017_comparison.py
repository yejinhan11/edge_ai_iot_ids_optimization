"""Partition, leakage prevention and validation-selected experiment checks."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

import compare_cicids2017_rf as experiment
from train_rf import time_split


class ComparisonTests(unittest.TestCase):
    def fixture(self):
        n = 240
        y = (np.arange(n) % 2).astype(np.int8)
        rng = np.random.default_rng(4)
        X = rng.normal(size=(n, 4)).astype(np.float32)
        X[:, 0] = y + rng.normal(0, .01, n)
        meta = pd.DataFrame(dict(source_pcap=np.repeat(['A', 'B'], n // 2),
                                 binary_label=y, row_in_file=np.arange(n),
                                 window_start_ts=np.arange(n)))
        return X, y, meta

    def test_window_outer_split_matches_existing_protocol(self):
        _, _, meta = self.fixture()
        split = experiment.partitions(meta)
        np.testing.assert_array_equal(split['fit'] | split['validation'], time_split(meta, .7, True))
        self.assertFalse((split['test'] & split['validation']).any())

    def test_whole_connection_groups_stay_together(self):
        _, _, meta = self.fixture()
        meta['split_group'] = np.arange(len(meta)) // 2
        split = experiment.partitions(meta, grouped=True)
        groups = {name: set(meta.loc[mask, 'split_group']) for name, mask in split.items()}
        self.assertFalse(groups['fit'] & groups['test'])
        self.assertFalse(groups['fit'] & groups['validation'])
        self.assertFalse(groups['validation'] & groups['test'])

    def test_imputer_never_uses_validation_or_test_statistics(self):
        raw = np.array([[1, 100], [3, np.nan], [9999999, 9], [np.nan, 50]], dtype=np.float32)
        result, medians, _ = experiment.impute_fit_only(raw, np.array([0, 1]))
        np.testing.assert_array_equal(medians, [2, 100])
        self.assertEqual(result[3, 0], 2)
        self.assertTrue(np.isnan(raw[3, 0]))

    def test_test_results_cannot_select_configuration(self):
        with self.assertRaises(ValueError):
            experiment.select_best([dict(evaluation='test', f1_macro=1)])

    def test_search_freeze_refit_and_serialization(self):
        X, y, meta = self.fixture()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(experiment, 'OUT', Path(tmp)):
            cfgs = [experiment.Config((0, 1, 2, 3)), experiment.Config((0, 1, 2, 3), 10)]
            rows = experiment.run_arm('legacy_windows', X, y, meta, ['a', 'b', 'c', 'd'],
                                      1000000, configs_override=cfgs)
            self.assertTrue(all(r['evaluation'] == 'test' for r in rows))
            self.assertTrue((Path(tmp) / 'legacy_windows/selection.json').exists())
            self.assertTrue((Path(tmp) / 'legacy_windows/validation_selected.joblib').exists())
            self.assertEqual({r['seed'] for r in rows if r['candidate'] == 'validation_selected'}, {42, 43, 44})
            experiment.report(rows)
            self.assertTrue((Path(tmp) / 'REPORT.md').exists())


if __name__ == '__main__':
    unittest.main()
