import io
import unittest
from unittest.mock import patch

from busybar.output import status


class OutputTests(unittest.TestCase):
    def test_status_adds_local_iso_timestamp_when_requested(self) -> None:
        stderr = io.StringIO()
        with patch("busybar.output.sys.stderr", stderr):
            status("Showing NVDA", timestamp=True)

        output = stderr.getvalue()
        self.assertRegex(
            output,
            r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}\] Showing NVDA\n$",
        )

    def test_status_remains_plain_without_timestamp(self) -> None:
        stderr = io.StringIO()
        with patch("busybar.output.sys.stderr", stderr):
            status("Connected via USB")

        self.assertEqual(stderr.getvalue(), "Connected via USB\n")


if __name__ == "__main__":
    unittest.main()
