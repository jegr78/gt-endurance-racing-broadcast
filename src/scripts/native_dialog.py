"""Show a fatal startup message to a user with no terminal — the windowed
`iro-ui` binary has no console to print to. Pure command builders plus a thin,
fully-injected dispatcher (tests pass fakes; nothing touches the system).
Used by src/iro_ui.py. Tests: tests/test_native_dialog.py."""
import subprocess
import sys

TITLE = "IRO Control Center"


def osascript_argv(message):
    """macOS: an `osascript -e 'display dialog ...'` argv. Double quotes in the
    message are neutralised so it cannot break out of the AppleScript string."""
    safe = message.replace('"', "'")
    return ["osascript", "-e",
            f'display dialog "{safe}" buttons {{"OK"}} default button "OK" '
            f'with icon stop with title "{TITLE}"']


def _win_msgbox(message):
    """Windows: a modal MessageBox via user32 (0x10 = MB_ICONERROR).
    ctypes is imported lazily here — importing it at module level would work on
    all platforms but is misleading (ctypes.windll only exists on Windows).
    The ruff rule set selects PLE only, not PLC, so PLC0415 is not enforced."""
    import ctypes  # noqa: PLC0415
    ctypes.windll.user32.MessageBoxW(0, message, TITLE, 0x10)


def notify(message, platform=sys.platform, run=subprocess.call, msgbox=None):
    """Surface `message` natively for the current OS. darwin -> osascript;
    win32 -> MessageBoxW; anything else -> stderr (the only safe fallback).
    `run`/`msgbox` are injected for tests."""
    if platform == "darwin":
        run(osascript_argv(message))
    elif platform.startswith("win"):
        (msgbox or _win_msgbox)(message)
    else:
        print(message, file=sys.stderr)
