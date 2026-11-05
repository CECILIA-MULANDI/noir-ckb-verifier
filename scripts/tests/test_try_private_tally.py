import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("try_private_tally", SCRIPTS / "try-private-tally.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def cell(tx, index, ckb, typed=False):
    return dict(out_point=dict(tx_hash=tx, index=hex(index)),
                output=dict(capacity=hex(ckb * 100_000_000), lock={}, type={"code_hash": "0x"} if typed else None))


class FundingCells(unittest.TestCase):
    def setUp(self):
        self.rpc = t.c.rpc
        self.calls = []

        def fake(url, method, params):
            self.calls.append((method, params))
            return dict(objects=[cell("0xa", 0, 100), cell("0xb", 1, 9000), cell("0xc", 0, 500, typed=True),
                                 cell("0xd", 2, 262), cell("0xe", 0, 261)])
        t.c.rpc = fake

    def tearDown(self):
        t.c.rpc = self.rpc

    def test_only_plain_cells_with_enough_ckb_largest_first(self):
        self.assertEqual(t.funding_cells("0x" + "11" * 20), ["0xb:1", "0xd:2"])

    def test_query_asks_for_empty_untyped_cells_of_the_owner(self):
        t.funding_cells("0x" + "11" * 20)
        method, (key, order, limit) = self.calls[0]
        self.assertEqual(method, "get_cells")
        self.assertEqual(key["script"]["args"], "0x" + "11" * 20)
        self.assertEqual(key["filter"], dict(output_data_len_range=["0x0", "0x1"], script_len_range=["0x0", "0x1"]))

    def test_minimum_covers_tally_change_and_fee(self):
        self.assertEqual(t.MIN_FUNDING, 262 * 100_000_000)


if __name__ == "__main__":
    unittest.main()
