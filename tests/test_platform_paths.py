import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from dps_assistant import engine, platform_paths, storage


class PortableTests(unittest.TestCase):
    def test_steam_library_parser_finds_a_game_on_another_drive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'steamapps').mkdir()
            library = root/'另一个游戏库'
            escaped = str(library).replace('\\', '\\\\')
            (root/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+escaped+'" } }', encoding='utf-8')
            self.assertIn(library, platform_paths.steam_libraries(root))
            game = library/'steamapps/common/DPS Desktop Pension Squad/DPS.exe'
            game.parent.mkdir(parents=True)
            game.touch()
            (game.parent/'GameAssembly.dll').touch()
            metadata = game.parent/'DPS_Data/il2cpp_data/Metadata/global-metadata.dat'
            metadata.parent.mkdir(parents=True)
            metadata.touch()
            with patch.object(platform_paths, 'registry_value', return_value=str(root)):
                self.assertEqual(platform_paths.find_game(), game.resolve())
            metadata.unlink()
            self.assertFalse(platform_paths.valid_game(game))

    def test_frozen_bridge_uses_the_bundled_executable(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', r'C:\portable\DPSAssistant.exe'):
            self.assertEqual(platform_paths.bridge_command(), [sys.executable, '--bridge-host'])

    def test_notice_is_persisted_once_outside_strategy_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(engine, 'DATA', root), patch.object(storage, 'DATA', root):
                first = engine.Engine(start=False)
                second = None
                try:
                    before = copy.deepcopy(first.config)
                    self.assertFalse(first.public_state()['preferences']['noticeAccepted'])
                    first.accept_notice()
                    self.assertEqual(first.config, before)
                    second = engine.Engine(start=False)
                    self.assertTrue(second.public_state()['preferences']['noticeAccepted'])
                    self.assertEqual(json.loads((root/'preferences.json').read_text(encoding='utf-8')), {'noticeAccepted': True})
                    self.assertEqual(first.public_state()['version'], '1.0.0')
                finally:
                    first.stop()
                    if second:
                        second.stop()
