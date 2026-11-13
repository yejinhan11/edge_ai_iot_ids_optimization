"""Guard label provenance and chronological partition boundaries for the new data."""
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from prepare_edge_iiotset import scenario
from train_rf import time_split


class EdgeTests(unittest.TestCase):
    def test_labels_require_explicit_capture_directory(self):
        self.assertEqual(scenario(Path('Normal traffic/Heart_Rate.pcap')),('Normal',0))
        self.assertEqual(scenario(Path('Attack traffic/DDoS TCP SYN Flood Attacks.pcap')),('DDoS_TCP_SYN',1))
        with self.assertRaises(ValueError):scenario(Path('other/DDoS TCP SYN Flood Attacks.pcap'))
        with self.assertRaises(ValueError):scenario(Path('Attack traffic/Port Scanning.pcap'))

    def test_omitted_cleaning_rows_do_not_shuffle_capture_order(self):
        frame=pd.DataFrame(dict(source_pcap=['normal']*4+['attack']*4,
            row_in_file=[1,2,7,9,1,2,7,9],binary_label=[0]*4+[1]*4))
        train=time_split(frame,.7);fit=time_split(frame,.56)
        np.testing.assert_array_equal(train,[True,True,False,False]*2)
        self.assertFalse(np.any(fit & ~train))
        self.assertEqual(set(frame.binary_label[train]),{0,1})
        self.assertEqual(set(frame.binary_label[~train]),{0,1})


if __name__=='__main__':unittest.main()
