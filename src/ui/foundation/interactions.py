"""Qt handler for framework-neutral application interaction events."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal, Slot

from src.events import ConfirmationRequested, communicate
from src.ui.foundation.dialogs import show_dialog_and_wait
from src.ui.foundation.overlay import OverlayWindow


class InteractionHandler(QObject):
    """Bridge EventBus callbacks to Qt slots without changing EventBus semantics."""

    _confirmation_requested = Signal(object)
    _overlay_shown = Signal(object)
    _overlay_cleared = Signal(object)
    _window_changed = Signal(object)

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._overlay_window = OverlayWindow(main_window)
        self._subscriptions = []
        self._confirmation_requested.connect(
            self._handle_confirmation,
            Qt.ConnectionType.QueuedConnection,
        )
        self._overlay_shown.connect(
            self._overlay_window.show_overlay,
            Qt.ConnectionType.QueuedConnection,
        )
        self._overlay_cleared.connect(
            self._overlay_window.clear_overlay,
            Qt.ConnectionType.QueuedConnection,
        )
        self._window_changed.connect(
            self._update_capture_geometry,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscribe(communicate.confirmation_requested, self._on_confirmation_requested)
        self._subscribe(communicate.overlay_shown, self._on_overlay_shown)
        self._subscribe(communicate.overlay_cleared, self._on_overlay_cleared)
        self._subscribe(communicate.window, self._on_window_changed)
        main_window.destroyed.connect(self._disconnect_from_event_bus)

    def _subscribe(self, signal, callback) -> None:
        signal.connect(callback)
        self._subscriptions.append((signal, callback))

    def _on_confirmation_requested(self, request: ConfirmationRequested) -> None:
        self._confirmation_requested.emit(request)

    def _on_overlay_shown(self, request) -> None:
        self._overlay_shown.emit(request)

    def _on_overlay_cleared(self, request) -> None:
        self._overlay_cleared.emit(request)

    def _on_window_changed(self, *args, **kwargs) -> None:
        self._window_changed.emit((args, kwargs))

    @Slot(object)
    def _update_capture_geometry(self, event) -> None:
        args, kwargs = event
        self._overlay_window.update_capture_geometry(*args, **kwargs)

    @Slot()
    def _disconnect_from_event_bus(self) -> None:
        for signal, callback in self._subscriptions:
            signal.disconnect(callback)
        self._subscriptions.clear()

    def _handle_confirmation(self, request: ConfirmationRequested) -> None:
        try:
            accepted = bool(
                show_dialog_and_wait(
                    request.title,
                    request.content,
                    parent=self._main_window,
                    copyable=request.copyable,
                    rich_text=request.rich_text,
                    hide_cancel=request.hide_cancel,
                    close_delay_seconds=request.close_delay_seconds or 0,
                )
            )
        except Exception:
            accepted = False
        request.resolve(accepted)


def install_interaction_handler(main_window) -> None:
    """Install the single Qt endpoint for application interaction events."""

    if hasattr(main_window, "_interaction_handler"):
        return
    main_window._interaction_handler = InteractionHandler(main_window)
