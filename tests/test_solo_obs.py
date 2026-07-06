#!/usr/bin/env python3
"""Stdlib checks for solo OBS templates + device localization (#303).
Run: python3 tests/test_solo_obs.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sa = _load("setup_assets", "src", "setup-assets.py")


def t_resolve_template_base():
    assert sa.resolve_template_base("endurance", "") == "GT_Endurance"
    assert sa.resolve_template_base("solo", "commentary") == "GT_Solo_Commentary"
    assert sa.resolve_template_base("solo", "pov") == "GT_Solo_POV"
    assert sa.resolve_template_base("solo", "") == "GT_Solo_Commentary"      # default
    assert sa.resolve_template_base("solo", "nonsense") == "GT_Solo_Commentary"
    assert sa.resolve_template_base("", "") == "GT_Endurance"                 # default kind


def _device_coll():
    return {"sources": [
        {"name": "Solo Capture", "uuid": "cap-uuid", "id": "av_capture_input",
         "versioned_id": "av_capture_input", "settings": {"device": "__RACECAST_CAPTURE__"}},
        {"name": "Solo Webcam", "uuid": "cam-uuid", "id": "av_capture_input",
         "versioned_id": "av_capture_input", "settings": {"device": "__RACECAST_WEBCAM__"}},
        {"name": "Overlay", "uuid": "ov", "id": "image_source", "settings": {}},
    ]}


def _byname(c, n):
    return next(s for s in c["sources"] if s["name"] == n)


def t_device_localize_windows():
    c = _device_coll()
    unset = sa.localize_device_sources(
        c, "win32", {"RACECAST_CAPTURE": "Cam:\\\\?\\usb#abc", "RACECAST_WEBCAM": "Logi:\\\\?\\usb#xyz"})
    cap = _byname(c, "Solo Capture")
    assert cap["id"] == cap["versioned_id"] == "dshow_input"
    assert cap["settings"] == {"video_device_id": "Cam:\\\\?\\usb#abc"}
    assert _byname(c, "Solo Webcam")["settings"] == {"video_device_id": "Logi:\\\\?\\usb#xyz"}
    assert unset == []


def t_device_localize_linux_and_darwin_keys():
    c = _device_coll()
    sa.localize_device_sources(c, "linux", {"RACECAST_CAPTURE": "/dev/video0",
                                            "RACECAST_WEBCAM": "/dev/video1"})
    assert _byname(c, "Solo Capture")["id"] == "v4l2_input"
    assert _byname(c, "Solo Capture")["settings"] == {"device_id": "/dev/video0"}
    c = _device_coll()
    sa.localize_device_sources(c, "darwin", {"RACECAST_CAPTURE": "AAAA", "RACECAST_WEBCAM": "BBBB"})
    assert _byname(c, "Solo Capture")["id"] == "av_capture_input"
    assert _byname(c, "Solo Capture")["settings"] == {"device": "AAAA"}


def t_device_localize_empty_env_warns_not_raises():
    c = _device_coll()
    unset = sa.localize_device_sources(c, "darwin", {})   # no device values
    assert sorted(unset) == ["Solo Capture", "Solo Webcam"]
    # source type still localized; device key present but empty (OBS shows black)
    assert _byname(c, "Solo Capture")["id"] == "av_capture_input"
    assert _byname(c, "Solo Capture")["settings"] == {"device": ""}


def t_device_localize_absent_sources_is_noop():
    c = {"sources": [{"name": "Overlay", "id": "image_source", "settings": {}}]}
    assert sa.localize_device_sources(c, "win32", {}) == []   # endurance: untouched


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
