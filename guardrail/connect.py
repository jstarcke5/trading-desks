#!/usr/bin/env python3
"""One-time browser login. Run this, click the link, log in. Nothing else needed.

Prints no token material, ever. Listens on loopback only, accepts exactly one callback,
validates the CSRF state, exchanges the code, stores the token 0600, and exits.
"""
import http.server, pathlib, sys, threading, urllib.parse, webbrowser, json

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rhauth  # noqa: E402

PORT = 8731
REDIRECT = "http://127.0.0.1:%d/callback" % PORT
result = {}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass                                        # never log the query string

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        result["code"] = (q.get("code") or [None])[0]
        result["state"] = (q.get("state") or [None])[0]
        result["error"] = (q.get("error") or [None])[0]
        ok = bool(result["code"]) and not result["error"]
        msg = ("Connected. You can close this tab and return to the terminal."
               if ok else "Login failed or was cancelled: %s" % (result["error"] or "no code"))
        body = ("<html><body style='font:16px -apple-system;padding:3rem'>%s</body></html>"
                % msg).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        threading.Thread(target=self.server.shutdown, daemon=True).start()

def main():
    client = rhauth.load_client()
    if not (client and client.get("client_id")):
        # Registration was previously a function nobody called, so the documented setup path
        # dead-ended here with an instruction that named no command.
        print("No registered client — registering this installation with the broker...")
        try:
            client = rhauth.register_client(REDIRECT)
        except Exception as e:
            print("Registration failed: %s: %s" % (type(e).__name__, str(e)[:200]))
            return 1
        print("Registered. client_id: %s" % client.get("client_id", "")[:8] + "…")
    cid = client["client_id"]
    verifier, state = rhauth.new_verifier(), rhauth.new_state()
    url = rhauth.authorize_url(cid, verifier, state, REDIRECT)

    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    print("Opening Robinhood login in your browser.")
    print("If it does not open, paste this URL:\n\n%s\n" % url)
    print("Waiting for the callback on %s ..." % REDIRECT)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    srv.serve_forever()          # exits after one callback
    srv.server_close()

    if result.get("error") or not result.get("code"):
        print("FAILED:", result.get("error") or "no authorization code returned"); return 1
    if not rhauth.state_ok(state, result.get("state")):
        print("FAILED: state mismatch — discarding this callback (possible CSRF)."); return 1
    try:
        rhauth.exchange_code(cid, result["code"], verifier, REDIRECT)
    except Exception as e:
        import urllib.error
        detail = e.read()[:200] if isinstance(e, urllib.error.HTTPError) else str(e)[:200]
        print("FAILED at token exchange:", type(e).__name__, detail); return 1
    print("\nConnected.", json.dumps(rhauth.status()))
    print("\nThis account can now be traded once you arm the guardrail. Before you do:")
    print("  - read guardrail/limits.json and replace every number with your own")
    print("  - understand that positions are not force-exited by a stop order")
    print("  - arming requires BOTH: touch guardrail/.armed AND export GUARDRAIL_UPSTREAM=http")
    return 0

if __name__ == "__main__":
    sys.exit(main())
