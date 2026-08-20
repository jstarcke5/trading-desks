#!/usr/bin/env python3
"""Robinhood OAuth for the GUARDRAIL. Stdlib only.

The credential lives here, behind the proxy -- never in a desk. If a desk held it, the desk
could call the broker directly and every limit in this system would be optional. One door,
always guarded.

This module authenticates and reads. It has no order-placing function of its own -- but the
SYSTEM does: see guardrail/live.py. Connecting a broker here is a real step toward live
trading, not a safe sandbox.
"""
import base64, hashlib, json, os, pathlib, secrets, time, urllib.parse, urllib.request

AUTHORIZE = "https://robinhood.com/oauth"
TOKEN     = "https://api.robinhood.com/oauth2/token/"
REGISTER  = "https://agent.robinhood.com/oauth/trading/register"
RESOURCE  = "https://agent.robinhood.com/mcp/trading"
SCOPE     = "internal"

HERE        = pathlib.Path(__file__).resolve().parent
TOKEN_PATH  = HERE / ".rh-token.json"       # gitignored, 0600
CLIENT_PATH = HERE / ".rh-client.json"      # gitignored, 0600
REFRESH_MARGIN = 120                        # refresh before it dies mid-order, not after

# ------------------------------------------------------------------ PKCE
def new_verifier():
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")[:128]

def challenge_for(verifier):
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

def new_state():
    return secrets.token_urlsafe(24)

def state_ok(ours, theirs):
    """CSRF. Constant-time, and an empty state is never valid."""
    if not ours or not theirs:
        return False
    return secrets.compare_digest(str(ours), str(theirs))

def redirect_ok(uri):
    """Loopback only. An off-machine redirect would hand the code to someone else."""
    try:
        p = urllib.parse.urlparse(uri)
    except ValueError:
        return False
    return p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")

# ------------------------------------------------------------------ URLs
def authorize_url(client_id, verifier, state, redirect_uri):
    if not redirect_ok(redirect_uri):
        raise ValueError("redirect_uri must be loopback: %r" % redirect_uri)
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge_for(verifier),   # never the verifier itself
        "code_challenge_method": "S256",
        "resource": RESOURCE,
    }
    return AUTHORIZE + "?" + urllib.parse.urlencode(q)

# ------------------------------------------------------------------ storage
def _write_private(path, obj):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    os.chmod(p, 0o600)
    return p

def save_token(tok, path=TOKEN_PATH):
    if not isinstance(tok, dict) or not tok.get("access_token"):
        raise ValueError("refusing to save a token with no access_token")
    return _write_private(path, tok)

def load_token(path=TOKEN_PATH):
    try:
        d = json.loads(pathlib.Path(path).read_text())
        return d if isinstance(d, dict) and d.get("access_token") else None
    except (OSError, ValueError):
        return None

def save_client(c, path=CLIENT_PATH):
    return _write_private(path, c)

def load_client(path=CLIENT_PATH):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None

def needs_refresh(tok, now=None):
    """Unknown expiry fails closed -- treated as expired."""
    now = time.time() if now is None else now
    exp = (tok or {}).get("expires_at")
    if not isinstance(exp, (int, float)):
        return True
    return now >= (exp - REFRESH_MARGIN)

# ------------------------------------------------------------------ network
def _post(url, payload, form=True):
    if form:
        body = urllib.parse.urlencode(payload).encode()
        ct = "application/x-www-form-urlencoded"
    else:
        body = json.dumps(payload).encode()
        ct = "application/json"
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": ct, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")

def register_client(redirect_uri, name="trading-canvas guardrail"):
    """Dynamic client registration. Creates a client_id; stores no secret if none is issued."""
    if not redirect_ok(redirect_uri):
        raise ValueError("redirect_uri must be loopback")
    out = _post(REGISTER, {
        "client_name": name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }, form=False)
    save_client(out)
    return out

def _stamp(tok):
    if isinstance(tok.get("expires_in"), (int, float)):
        tok["expires_at"] = time.time() + float(tok["expires_in"])
    return tok

def exchange_code(client_id, code, verifier, redirect_uri):
    tok = _post(TOKEN, {"grant_type": "authorization_code", "code": code,
                        "client_id": client_id, "redirect_uri": redirect_uri,
                        "code_verifier": verifier, "resource": RESOURCE})
    return save_token(_stamp(tok)) and load_token()

def refresh(client_id, refresh_token):
    tok = _post(TOKEN, {"grant_type": "refresh_token", "refresh_token": refresh_token,
                        "client_id": client_id, "scope": SCOPE, "resource": RESOURCE})
    if not tok.get("refresh_token"):
        tok["refresh_token"] = refresh_token          # some servers omit it on refresh
    return save_token(_stamp(tok)) and load_token()

def bearer():
    """Return a usable access token, refreshing if needed. None if not connected."""
    tok, client = load_token(), load_client()
    if not tok:
        return None
    if needs_refresh(tok):
        if not (client and client.get("client_id") and tok.get("refresh_token")):
            return None
        try:
            tok = refresh(client["client_id"], tok["refresh_token"])
        except Exception:
            return None
    return (tok or {}).get("access_token")

def status():
    """Human-readable, and NEVER prints any token material."""
    c, t = load_client(), load_token()
    return {
        "client_registered": bool(c and c.get("client_id")),
        "token_present": bool(t),
        "token_valid": bool(t) and not needs_refresh(t),
        # This module authenticates and reads; it has no order function. That is NOT a
        # statement about the system: guardrail/live.py and server.py DO place orders
        # once armed. Reporting "can_place_orders: false" here was a false assurance
        # delivered at the exact moment a user hands over broker credentials.
        "this_module_can_place_orders": False,
    }
