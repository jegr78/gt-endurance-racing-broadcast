import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
import discord_oauth as do


def t_authorize_url_has_required_params():
    u = do.authorize_url("cid123", "https://host.ts.net/console/oauth/callback", "st.0.sig")
    assert u.startswith(do.AUTHORIZE_ENDPOINT + "?")
    assert "client_id=cid123" in u
    assert "scope=identify" in u
    assert "response_type=code" in u
    assert "redirect_uri=https%3A%2F%2Fhost.ts.net%2Fconsole%2Foauth%2Fcallback" in u
    assert "state=st.0.sig" in u


def t_state_roundtrip_valid():
    s = do.sign_state("secret", "abc123", 1000)
    assert do.verify_state("secret", s, now=1100, ttl=300) is True


def t_state_expired():
    s = do.sign_state("secret", "abc123", 1000)
    assert do.verify_state("secret", s, now=1400, ttl=300) is False   # 400s > 300


def t_state_tampered_or_wrong_secret():
    s = do.sign_state("secret", "abc123", 1000)
    assert do.verify_state("WRONG", s, now=1100, ttl=300) is False
    assert do.verify_state("secret", s + "x", now=1100, ttl=300) is False
    assert do.verify_state("secret", "not.a.state", now=1100, ttl=300) is False


def t_parse_identity():
    assert do.parse_identity({"id": "1", "username": "Jens_Gross"}) == "jens_gross"
    assert do.parse_identity({"id": "1"}) == ""
    assert do.parse_identity("garbage") == ""


def t_match_subject_case_insensitive():
    dm = {"jens_gross": "Jens Gross"}
    assert do.match_subject("Jens_Gross", dm) == "Jens Gross"
    assert do.match_subject("nobody", dm) is None
    assert do.match_subject("", dm) is None


def t_valid_redirect_host():
    assert do.valid_redirect_host("box.tail1234.ts.net") is True
    assert do.valid_redirect_host("evil.com") is False
    assert do.valid_redirect_host("box.ts.net\r\nX") is False
    assert do.valid_redirect_host("") is False
    # Hyphen-boundary hosts must be rejected
    assert do.valid_redirect_host("-evil.ts.net") is False
    assert do.valid_redirect_host("bad-.ts.net") is False


def t_state_future_dated_rejected():
    s = do.sign_state("secret", "abc123", 2000)
    assert do.verify_state("secret", s, now=1000, ttl=300) is False  # ts in the future


for _n, _f in sorted(globals().items()):
    if _n.startswith("t_") and callable(_f):
        _f(); print("ok", _n)
print("all discord_oauth tests passed")
