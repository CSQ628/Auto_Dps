import unittest
from unittest.mock import Mock, patch
from dps_assistant.tray import SystemTray


class TrayTests(unittest.TestCase):
    def test_tray_controls_use_the_same_persistent_configuration_as_the_web(self):
        engine=Mock();engine.config={'running':True}
        engine.update.side_effect=lambda value:engine.config.update(value)
        server=Mock();server.origin='http://127.0.0.1:17860'
        tray=SystemTray(engine,server,'unused.ico')
        tray.command(2);self.assertFalse(engine.config['running'])
        tray.command(2);self.assertTrue(engine.config['running'])
        with patch('dps_assistant.tray.webbrowser.open') as browser:
            tray.command(1);browser.assert_called_once_with(server.origin)
        tray.command(3);server.shutdown.assert_called_once()
