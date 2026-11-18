import unittest
from unittest.mock import Mock, patch

import psutil
from performance import cpu_threads, background_priority


class PerformanceTests(unittest.TestCase):
    def test_thread_budget_uses_physical_cores_and_handles_unknown_hardware(self):
        for physical, logical, expected in [(8, 16, 8), (4, 8, 4), (2, 4, 2), (1, 1, 1), (None, 16, 8)]:
            with self.subTest(physical=physical, logical=logical):
                with patch('performance.psutil.cpu_count', side_effect=lambda logical=True: physical if not logical else logical_count):
                    logical_count = logical
                    self.assertEqual(cpu_threads(), expected)

    def test_priority_is_restored_after_error(self):
        process = Mock()
        process.nice.return_value = psutil.NORMAL_PRIORITY_CLASS
        with patch('performance.os.name', 'nt'), patch('performance.psutil.Process', return_value=process):
            with self.assertRaises(ValueError), background_priority():
                self.assertEqual(process.nice.call_args.args, (psutil.BELOW_NORMAL_PRIORITY_CLASS,))
                raise ValueError('cancelled or failed work')
        self.assertEqual(process.nice.call_args.args, (psutil.NORMAL_PRIORITY_CLASS,))


if __name__ == '__main__':
    unittest.main()
