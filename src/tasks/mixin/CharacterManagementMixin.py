import threading
import time

from ok import Logger, TriggerTask, og

from src.char.core.CharFactory import get_char_by_id, get_char_feature_by_pos
from src.char.custom.CustomCharManager import CustomCharManager
from src.events import (
    ComboTestRequested,
    TeamScanCompleted,
    TeamScanRequested,
    TeamScanResult,
    communicate,
)

logger = Logger.get_logger(__name__)


class CharacterManagementMixin(TriggerTask):
    """Task-side operations used by character-management tools."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._character_management_ocr_lock = threading.Lock()
        communicate.team_scan_requested.connect(self._request_team_scan)
        communicate.combo_test_requested.connect(self._request_combo_test)

    def _request_team_scan(self, _request: TeamScanRequested) -> None:
        og.app.start_controller.handler.post(self._scan_team)

    def _request_combo_test(self, request: ComboTestRequested) -> None:
        og.app.start_controller.handler.post(lambda: self._test_combo(request))

    def _scan_team(self) -> None:
        error = self.prepare_game_capture()
        if error:
            communicate.team_scan_completed.emit(TeamScanCompleted((), error))
            return

        try:
            in_team, _, count = self.in_team()
            if not in_team or count == 0:
                raise RuntimeError(self.tr("队伍不存在"))
            if count < 2:
                raise RuntimeError(self.tr("队伍人数少于2人"))

            manager = CustomCharManager()
            results = []
            frame = self.frame
            for index in range(count):
                image, width, height = get_char_feature_by_pos(self, index, frame=frame)
                if image is None or image.size <= 0:
                    continue
                _, character_id, confidence = manager.match_feature(self, image)
                results.append(
                    TeamScanResult(index, image, width, height, character_id, confidence)
                )
            communicate.team_scan_completed.emit(TeamScanCompleted(tuple(results)))
        except Exception as error:
            error_message = str(error).strip() or error.__class__.__name__
            logger.exception("Team scan failed: %s", error_message)
            communicate.team_scan_completed.emit(TeamScanCompleted((), error_message))

    def _test_combo(self, request: ComboTestRequested) -> None:
        if self.prepare_game_capture():
            return

        from src.char.custom.CustomChar import CustomChar

        if request.implementation_id:
            test_char = get_char_by_id(
                self,
                index=0,
                char_id=request.character_id,
                impl_id=request.implementation_id,
            )
        else:
            test_char = CustomChar(self, index=0, char_id=request.character_id)

        original_ocr = self.ocr
        original_chars = self.chars
        original_sleep = self.sleep

        def locked_ocr(*args, **kwargs):
            with self._character_management_ocr_lock:
                return original_ocr(*args, **kwargs)

        def direct_sleep(timeout):
            if timeout > 0:
                time.sleep(timeout)
            return True

        self.ocr = locked_ocr
        self.chars = [test_char]
        self.sleep = direct_sleep
        try:
            test_char.is_current_char = True
            test_char.switch_next_char = lambda *args, **kwargs: None
            if isinstance(test_char, CustomChar):
                test_char.combo_str = request.combo_text
                test_char._compile_combo()
            test_char.perform()
        finally:
            self.sleep = original_sleep
            self.chars = original_chars
            self.ocr = original_ocr
