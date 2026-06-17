"""Automate the one-time Tailscale-tailnet prerequisites for the Commentator
Cockpit Funnel (issue #191), driven by `racecast cockpit setup-funnel`.

What it does, via the Tailscale Admin API authenticated with an OAuth client:
  1. enable MagicDNS                          (dns/preferences — a single, safe pref)
  2. add the `funnel` nodeAttr to the policy  (acl GET -> merge -> POST, ETag-guarded)
HTTPS-certificate enablement has no reliable public API and stays a one-click
admin step — we detect what we can and print the reminder.

Split: the policy/preference reasoning is PURE (unit-tested below the API helpers);
the HTTP is a thin stdlib layer. Stdlib only — no third-party deps.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.tailscale.com/api/v2"
OAUTH_URL = API + "/oauth/token"
FUNNEL_ATTR = "funnel"
DEFAULT_TARGET = "autogroup:member"


# ----------------------------- pure logic --------------------------------

def magicdns_enabled(prefs):
    """True iff the tailnet DNS preferences have MagicDNS on. Pure."""
    return bool((prefs or {}).get("magicDNS"))


def acl_has_funnel(acl):
    """True iff the policy already grants the 'funnel' nodeAttr to anyone. Pure.
    Conservative: ANY funnel grant counts (we never append a duplicate; targeting
    is left to the admin)."""
    for entry in (acl or {}).get("nodeAttrs") or []:
        if isinstance(entry, dict) and FUNNEL_ATTR in (entry.get("attr") or []):
            return True
    return False


def add_funnel_nodeattr(acl, target=DEFAULT_TARGET):
    """Return (new_acl, changed): a shallow copy of *acl* with a
    {"target":[target],"attr":["funnel"]} nodeAttr appended, unless a funnel grant
    already exists. Preserves every other key. Pure — does not mutate the input."""
    if acl_has_funnel(acl):
        return acl, False
    new = dict(acl or {})
    new["nodeAttrs"] = list(new.get("nodeAttrs") or []) + [
        {"target": [target], "attr": [FUNNEL_ATTR]}]
    return new, True


def setup_plan(prefs, acl):
    """Ordered list of human-readable changes still needed. [] when ready (modulo
    HTTPS, which has no API). Pure."""
    steps = []
    if not magicdns_enabled(prefs):
        steps.append("enable MagicDNS")
    if not acl_has_funnel(acl):
        steps.append("add the 'funnel' nodeAttr to the tailnet policy")
    return steps


# ----------------------------- thin HTTP ---------------------------------

def fetch_token(client_id, client_secret, timeout=15):
    """Exchange OAuth client credentials for a short-lived API access token."""
    data = urllib.parse.urlencode(
        {"client_id": client_id, "client_secret": client_secret}).encode()
    req = urllib.request.Request(OAUTH_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (https)
        return json.loads(r.read())["access_token"]


def _req(token, method, path, body=None, etag=None, accept=None, timeout=20):
    headers = {"Authorization": "Bearer " + token}
    if accept:
        headers["Accept"] = accept
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if etag:
        headers["If-Match"] = etag
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (https)
        return r.status, dict(r.headers), r.read()


def get_dns_prefs(token, tailnet="-"):
    _s, _h, body = _req(token, "GET", f"/tailnet/{tailnet}/dns/preferences")
    return json.loads(body)


def enable_magicdns(token, tailnet="-"):
    return _req(token, "POST", f"/tailnet/{tailnet}/dns/preferences",
                body={"magicDNS": True})


def get_acl(token, tailnet="-"):
    """(acl_dict, etag). Accept application/json so the HuJSON policy parses
    cleanly (NOTE: this drops comments — callers back up before writing)."""
    _s, headers, body = _req(token, "GET", f"/tailnet/{tailnet}/acl",
                             accept="application/json")
    return json.loads(body), headers.get("ETag")


def put_acl(token, acl, etag, tailnet="-"):
    return _req(token, "POST", f"/tailnet/{tailnet}/acl", body=acl, etag=etag)
