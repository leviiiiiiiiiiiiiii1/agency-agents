import tempfile
import unittest
from pathlib import Path

from auto_trader_iq.settings import (
    find_tesseract_executable,
    load_settings,
    save_settings,
)


class SettingsPersistenceTests(unittest.TestCase):
    def test_settings_are_written_atomically_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "nested" / "config.json"
            settings = {
                "timeframe": "M1",
                "tesseract_executable": "tesseract.exe",
                "excluded_regions": [{"left": 10, "top": 20, "width": 30, "height": 40}],
            }

            save_settings(config_path, settings)

            self.assertEqual(load_settings(config_path), settings)
            self.assertFalse(config_path.with_name(f".{config_path.name}.tmp").exists())

    def test_non_object_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(config_path)


class TesseractDiscoveryTests(unittest.TestCase):
    def test_explicit_environment_override_wins(self):
        executable = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        self.assertEqual(
            find_tesseract_executable(
                {"TESSERACT_CMD": executable, "PATH": ""}, platform="win32"
            ),
            executable,
        )

    def test_discovers_standard_windows_install_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            program_files = Path(temp_dir) / "Program Files"
            executable = program_files / "Tesseract-OCR" / "tesseract.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()

            self.assertEqual(
                find_tesseract_executable(
                    {
                        "ProgramFiles": str(program_files),
                        "ProgramFiles(x86)": str(Path(temp_dir) / "Program Files (x86)"),
                        "PATH": "",
                    },
                    platform="win32",
                ),
                str(executable),
            )

    def test_returns_empty_when_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(
                find_tesseract_executable(
                    {
                        "ProgramFiles": temp_dir,
                        "ProgramFiles(x86)": temp_dir,
                        "PATH": "",
                    },
                    platform="win32",
                ),
                "",
            )


if __name__ == "__main__":
    unittest.main()
