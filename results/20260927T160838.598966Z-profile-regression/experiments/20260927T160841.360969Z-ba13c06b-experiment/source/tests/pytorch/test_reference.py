"""CPU-only tests for the floating-point reference checker (requires torch)."""
from pathlib import Path
import sys
import unittest

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'experiments/pytorch'))
from device_lab import compare_output


class ReferenceTests(unittest.TestCase):
    def test_small_roundoff_is_accepted(self):
        result = compare_output(torch, torch.tensor([1.0, 2.000001]), torch.tensor([1.0, 2.0]))
        self.assertEqual(result['status'], 'PASS')

    def test_corrupted_result_is_rejected(self):
        with self.assertRaises(AssertionError):
            compare_output(torch, torch.tensor([1.0, 3.0]), torch.tensor([1.0, 2.0]))

    def test_nonfinite_is_rejected_even_when_matching(self):
        for value in [float('nan'), float('inf'), -float('inf')]:
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, 'nonfinite'):
                compare_output(torch, torch.tensor([value]), torch.tensor([value]))

    def test_broadcastable_shape_mismatch_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'shape mismatch'):
            compare_output(torch, torch.ones(2, 2), torch.ones(1, 2))


if __name__ == '__main__':
    unittest.main()
