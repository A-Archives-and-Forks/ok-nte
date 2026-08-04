import unittest
from unittest.mock import Mock, patch

from ok import TaskDisabledException

from src import LAUNCHER_EXE
from src.tasks.LauncherTask import LauncherButtonState, LauncherTask


class TestLauncherTask(unittest.TestCase):
    def _make_task(self):
        task = object.__new__(LauncherTask)
        task.log_info = Mock()
        task.log_warning = Mock()
        task.log_info_gated = Mock()
        task.sleep = Mock()
        task.capture_config = Mock()
        task.capture_config.GAME_CAPTURE_CONFIG = {"windows": {"hwnd_class": "UnrealWindow"}}
        task.capture_config.LAUNCHER_CAPTURE_CONFIG = {
            "windows": {"hwnd_class": "Qt51517QWindowOwnDC"}
        }
        return task

    def test_hidden_launcher_is_shown_before_capture(self):
        task = self._make_task()

        with (
            patch("src.tasks.LauncherTask.win32gui.IsIconic", side_effect=[False, False]),
            patch("src.tasks.LauncherTask.win32gui.IsWindowVisible", side_effect=[False, True]),
            patch("src.tasks.LauncherTask.win32gui.ShowWindow") as show_window,
        ):
            self.assertTrue(task._restore_window_if_minimized(123, "NTEGame.exe"))

        show_window.assert_called_once_with(123, 5)

    def test_capture_stops_when_launcher_cannot_be_shown(self):
        task = self._make_task()
        task.capture_config = Mock()
        task._ensure_launcher_visible = Mock(return_value=False)

        with self.assertRaisesRegex(TaskDisabledException, "Launcher window is not visible"):
            task._capture_launcher()

    def test_start_game_does_not_accept_hidden_launcher_before_click(self):
        task = self._make_task()
        task._find_process = Mock(return_value=None)
        task._ensure_launcher_visible = Mock(return_value=True)
        task._launcher_button_state = Mock(return_value=(LauncherButtonState.START, "start_button"))
        task._is_launcher_hidden_or_minimized = Mock(return_value=True)
        task.box_of_screen = Mock()
        task.find_one = Mock(return_value=None)
        task.click = Mock()

        with patch("src.tasks.LauncherTask.time.time", side_effect=[0, 0, 0]):
            self.assertTrue(task._click_start_game())

        task.click.assert_called_once_with("start_button", after_sleep=2)

    def test_find_process_window_uses_launcher_capture_window_class(self):
        task = self._make_task()
        proc = {"pid": 1}
        task._find_process = Mock(return_value=proc)
        task._find_window_for_process = Mock(return_value=123)

        self.assertEqual((proc, 123), task._find_process_window(LAUNCHER_EXE))

        task._find_window_for_process.assert_called_once_with(
            proc,
            hwnd_class="Qt51517QWindowOwnDC",
            require_title=False,
        )
