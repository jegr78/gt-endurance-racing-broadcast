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


if __name__ == "__main__":
    t_platform_of(); print("ok")
