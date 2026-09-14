"""Hold-to-talk.

The only thing in this daemon that opens the microphone. There is no wake word,
no voice-activity trigger, and no always-listening path — the mic opens while
the key is physically held and closes on release, and nothing else can ask for
it.

A CoreGraphics event tap rather than `pynput`: same job, MIT instead of
LGPLv3, one fewer dependency on a machine with keychain reach.
"""

from __future__ import annotations

import platform
import threading
from typing import Callable

Callback = Callable[[], None]


class PushToTalkUnavailable(RuntimeError):
    pass


class BasePushToTalk:
    """Press and release, nothing else. Subclasses supply the event source."""

    def __init__(self, keycode: int, on_press: Callback, on_release: Callback) -> None:
        self.keycode = keycode
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._lock = threading.Lock()

    @property
    def held(self) -> bool:
        return self._held

    # Subclasses call these; they are idempotent so a repeated key-down event
    # (macOS auto-repeat) cannot open the mic twice.
    def _press(self) -> None:
        with self._lock:
            if self._held:
                return
            self._held = True
        self._on_press()

    def _release(self) -> None:
        with self._lock:
            if not self._held:
                return
            self._held = False
        self._on_release()

    def run(self) -> None:  # pragma: no cover - platform specific
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - platform specific
        raise NotImplementedError


class DarwinPushToTalk(BasePushToTalk):
    """CGEventTap on key-down/key-up and the modifier-flags stream.

    Accessibility permission is required. Without it the tap is created but
    never fires, which would look exactly like a broken key — so creation is
    checked and reported rather than left to fail silently.
    """

    def __init__(self, keycode: int, on_press: Callback, on_release: Callback) -> None:
        super().__init__(keycode, on_press, on_release)
        self._tap = None
        self._loop = None

    def run(self) -> None:  # pragma: no cover - requires macOS + accessibility
        import Quartz
        from CoreFoundation import (CFMachPortCreateRunLoopSource, CFRunLoopAddSource,
                                    CFRunLoopGetCurrent, CFRunLoopRun, kCFRunLoopCommonModes)

        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
                | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))

        def handler(proxy, etype, event, refcon):
            try:
                code = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                if code == self.keycode:
                    if etype == Quartz.kCGEventKeyDown:
                        self._press()
                    elif etype == Quartz.kCGEventKeyUp:
                        self._release()
                    elif etype == Quartz.kCGEventFlagsChanged:
                        # Modifier keys (fn included) report state in the flags.
                        flags = Quartz.CGEventGetFlags(event)
                        down = bool(flags & Quartz.kCGEventFlagMaskSecondaryFn)
                        self._press() if down else self._release()
            except Exception:  # noqa: BLE001 - never let the tap die on one event
                pass
            return event

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly, mask, handler, None)
        if not self._tap:
            raise PushToTalkUnavailable(
                "could not create the event tap. Grant Accessibility permission to "
                "the Desk daemon in System Settings > Privacy & Security."
            )
        source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._loop, source, kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        CFRunLoopRun()

    def stop(self) -> None:  # pragma: no cover - platform specific
        if self._tap is not None:
            import Quartz
            Quartz.CGEventTapEnable(self._tap, False)
        if self._loop is not None:
            from CoreFoundation import CFRunLoopStop
            CFRunLoopStop(self._loop)


class ManualPushToTalk(BasePushToTalk):
    """Driven by explicit calls. Used by the bench and the tests — never by the
    daemon, which has exactly one key source."""

    def press(self) -> None:
        self._press()

    def release(self) -> None:
        self._release()

    def run(self) -> None:
        return

    def stop(self) -> None:
        return


def create(keycode: int, on_press: Callback, on_release: Callback) -> BasePushToTalk:
    if platform.system() != "Darwin":
        raise PushToTalkUnavailable(
            "hold-to-talk needs macOS. Desk does not run a keyboard hook anywhere else."
        )
    return DarwinPushToTalk(keycode, on_press, on_release)
