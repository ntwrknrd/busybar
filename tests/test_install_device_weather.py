import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "install_weather", Path(__file__).resolve().parents[1] / "scripts/install_device_weather.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallWeatherTests(unittest.TestCase):
    def bar(self, *, version="1.2.4", cloud=False):
        bar = Mock(is_cloud=cloud)
        bar.status_firmware.return_value = SimpleNamespace(version=version)
        return bar

    def run_install(self, bar):
        with patch.object(installer, "resolve", return_value=(bar, SimpleNamespace(name="test"))):
            installer.main()

    def test_rejects_unsupported_firmware_before_writing(self):
        bar = self.bar(version="1.1.1")
        with self.assertRaisesRegex(RuntimeError, "only for 1.2.4"):
            self.run_install(bar)
        bar.storage_write.assert_not_called()
        bar.close.assert_called_once()

    def test_rejects_cloud_before_writing(self):
        bar = self.bar(cloud=True)
        with self.assertRaisesRegex(RuntimeError, "local"):
            self.run_install(bar)
        bar.storage_write.assert_not_called()

    def test_preserves_existing_different_app(self):
        bar = self.bar()
        bar.storage_list.return_value = SimpleNamespace(
            list=[SimpleNamespace(name=installer.APP_ID)]
        )
        bar.storage_read.return_value = b"someone else's app"
        with self.assertRaisesRegex(RuntimeError, "preserve it"):
            self.run_install(bar)
        bar.storage_write.assert_not_called()
        bar.storage_mkdir.assert_not_called()

    def test_upload_readback_failure_does_not_publish_manifest_or_flag(self):
        bar = self.bar()
        bar.storage_list.return_value = SimpleNamespace(list=[])
        bar.storage_read.return_value = b"truncated"
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            self.run_install(bar)
        targets = [call.args[0] for call in bar.storage_write.call_args_list]
        self.assertEqual(targets, [f"{installer.REMOTE}/scripts/main.js"])


if __name__ == "__main__":
    unittest.main()
