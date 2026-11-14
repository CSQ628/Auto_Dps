"""Discovery and bridge errors are not evidence that a game needs relaunching."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import psutil
from dps_assistant import engine,runtime,storage


class PresenceTests(unittest.TestCase):
    def process(self,pid=1,name='DPS.exe'):
        p=Mock(pid=pid);p.name.return_value=name
        p.exe.side_effect=psutil.AccessDenied(pid)
        return p

    def test_process_with_unreadable_executable_and_missing_metadata_still_exists(self):
        p=self.process()
        with patch.object(runtime.psutil,'process_iter',return_value=[p]),patch.object(runtime,'box_for',return_value=''):
            self.assertEqual(runtime.game_presence(''),'present')
        p.exe.assert_not_called()

    def test_environments_are_checked_independently_without_shared_process_info(self):
        host,box=self.process(1),self.process(2)
        with patch.object(runtime.psutil,'process_iter',return_value=[host,box]),patch.object(runtime,'box_for',side_effect=lambda pid:{1:'',2:'sandbox'}[pid]):
            self.assertEqual(runtime.game_presence(''),'present')
            self.assertEqual(runtime.game_presence('sandbox'),'present')
            self.assertEqual(runtime.game_presence('other'),'absent')

    def test_access_or_sandbox_query_failure_is_unknown_but_exited_process_is_absent(self):
        p=self.process()
        with patch.object(runtime.psutil,'process_iter',return_value=[p]):
            p.name.side_effect=psutil.AccessDenied(1)
            self.assertEqual(runtime.game_presence(),'unknown')
            p.name.side_effect=psutil.NoSuchProcess(1)
            self.assertEqual(runtime.game_presence(),'absent')
            p.name.side_effect=None
            with patch.object(runtime,'box_for',side_effect=OSError('query failed')):
                self.assertEqual(runtime.game_presence(),'unknown')

    def test_launch_rechecks_immediately_before_popen_and_never_uses_bridge_failure_to_restart(self):
        for states in (['present'],['unknown'],['absent','present'],['absent','unknown']):
            with self.subTest(states=states),patch.object(runtime,'game_presence',side_effect=states),\
                    patch.object(runtime,'GAME',Path(__file__)),patch.object(runtime.subprocess,'Popen') as spawn:
                self.assertIsNone(runtime.launch());spawn.assert_not_called()
        with patch.object(runtime,'game_presence',return_value='absent'),patch.object(runtime,'GAME',Path(__file__)),\
                patch.object(runtime.subprocess,'Popen') as spawn:
            self.assertEqual(runtime.launch(),spawn.return_value.pid)
            spawn.assert_called_once()

    def test_sandbox_query_only_recognizes_documented_outside_box_status(self):
        with tempfile.TemporaryDirectory() as folder:
            dll=Path(folder)/'SbieDll.dll';dll.touch()
            for code in (0xc0000022,0xc0000001):
                with patch.object(runtime,'SBIE',Path(folder)),patch.object(runtime,'_api',return_value=code):
                    with self.assertRaises(OSError):runtime.box_for(1)
            with patch.object(runtime,'SBIE',Path(folder)),patch.object(runtime,'_api',return_value=-1073741813):
                self.assertEqual(runtime.box_for(1),'')


class LaunchSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)
        self.patches=[patch.object(engine,'DATA',self.path),patch.object(storage,'DATA',self.path)]
        for p in self.patches:p.start()
        self.app=engine.Engine(start=False)
    def tearDown(self):
        self.app.stop()
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    def test_repeated_discovery_misses_or_permission_failures_never_relaunch_existing_game(self):
        for presence in ('present','unknown'):
            with patch.object(engine,'game_presence',return_value=presence),patch.object(engine,'launch') as launch:
                for now in (1000,1200,1800,4000):self.app.launch_missing(set(),['sandbox'],now)
                launch.assert_not_called()
            self.assertTrue(self.app.config['running']);self.assertFalse(self.app.config['instances'])

    def test_real_exit_launches_once_and_retry_reservation_survives_restart(self):
        with patch.object(engine,'game_presence',return_value='absent'),patch.object(engine,'launch') as launch:
            self.app.launch_missing({'sandbox'},['sandbox'],1000)
            launch.assert_called_once_with('',None)
            restarted=engine.Engine(start=False)
            try:restarted.launch_missing({'sandbox'},['sandbox'],1001)
            finally:restarted.stop()
            self.assertEqual(launch.call_count,1)

    def test_host_stays_running_while_only_missing_sandbox_launches(self):
        with patch.object(engine,'game_presence',side_effect=lambda box:'present' if not box else 'absent'),patch.object(engine,'launch') as launch:
            self.app.launch_missing(set(),['sandbox'],1000)
            launch.assert_called_once_with('sandbox',None)
