# tests/test_platform.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "relay"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "feeds", os.path.join(os.path.dirname(__file__), "..", "src", "relay", "racecast-feeds.py"))
feeds = importlib.util.module_from_spec(spec); spec.loader.exec_module(feeds)


def t_platform_of():
    assert feeds.platform_of("https://www.youtube.com/watch?v=abc") == "youtube"
    assert feeds.platform_of("https://youtu.be/abc") == "youtube"
    assert feeds.platform_of("https://www.twitch.tv/somechannel") == "twitch"
    assert feeds.platform_of("https://TWITCH.TV/Chan") == "twitch"      # case-insensitive
    assert feeds.platform_of("https://m.twitch.tv/chan") == "twitch"    # subdomain
    # bare UC id (channel_url turns it into a youtube URL) -> youtube
    assert feeds.platform_of("UC1234567890123456789012") == "youtube"
    # userinfo trick must NOT be seen as twitch
    assert feeds.platform_of("https://twitch.tv@evil.com/") == "youtube"


def t_serve_cmd_youtube():
    cmd = feeds.streamlink_serve_cmd("https://hls.example/x.m3u8", 53001)
    assert "--twitch-low-latency" not in cmd
    assert cmd[-2:] == ["https://hls.example/x.m3u8", "best"]
    assert "--" in cmd and cmd.index("--") < cmd.index("https://hls.example/x.m3u8")


def t_serve_cmd_twitch():
    cmd = feeds.streamlink_serve_cmd("https://www.twitch.tv/chan", 53002, platform="twitch")
    assert "--twitch-low-latency" in cmd
    assert "--twitch-disable-ads" not in cmd            # deprecated; ads filtered automatically
    assert cmd[cmd.index("--hls-live-edge") + 1] == "2"  # tighter than the default 4
    assert cmd[-2:] == ["https://www.twitch.tv/chan", "best"]


def t_serve_cmd_twitch_token():
    cmd = feeds.streamlink_serve_cmd("https://www.twitch.tv/chan", 53002,
                                     platform="twitch", twitch_token="abc123")
    i = cmd.index("--twitch-api-header")
    assert cmd[i + 1] == "Authorization=OAuth abc123"
    assert i < cmd.index("--")                          # header is an option, before the URL


def t_ssai_markers():
    clean = "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:2.0,\nseg0.ts\n#EXTINF:2.0,\nseg1.ts\n"
    assert feeds.manifest_has_ssai_markers(clean) is False
    cue = clean + "#EXT-X-CUE-OUT:30.0\n#EXTINF:2.0,\nad0.ts\n"
    assert feeds.manifest_has_ssai_markers(cue) is True
    daterange = clean + '#EXT-X-DATERANGE:ID="ad1",CLASS="twitch-stitched-ad",START-DATE="..."\n'
    assert feeds.manifest_has_ssai_markers(daterange) is True
    assert feeds.manifest_has_ssai_markers("") is False
    assert feeds.manifest_has_ssai_markers(None) is False


if __name__ == "__main__":
    t_platform_of(); t_serve_cmd_youtube(); t_serve_cmd_twitch(); t_serve_cmd_twitch_token(); t_ssai_markers(); print("ok")
