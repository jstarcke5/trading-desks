"""OAuth client for the guardrail. The credential lives BEHIND the guardrail, never in a desk."""
import os, sys, tempfile, unittest, pathlib, base64, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import rhauth  # noqa: E402


class PkceTest(unittest.TestCase):
    def test_verifier_is_long_enough_and_urlsafe(self):
        v = rhauth.new_verifier()
        self.assertGreaterEqual(len(v), 43)
        self.assertLessEqual(len(v), 128)
        self.assertNotIn("=", v)
        self.assertNotIn("+", v)
        self.assertNotIn("/", v)

    def test_challenge_is_s256_of_verifier(self):
        v = "test-verifier-value-that-is-long-enough-to-be-valid-xx"
        want = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
        self.assertEqual(rhauth.challenge_for(v), want)

    def test_verifiers_are_not_reused(self):
        self.assertNotEqual(rhauth.new_verifier(), rhauth.new_verifier())


class AuthorizeUrlTest(unittest.TestCase):
    def test_url_carries_pkce_state_and_resource(self):
        u = rhauth.authorize_url("cid-123", "verifier-x-long-enough-for-pkce-aaaaaaaaaaaaaaa",
                                 "st-abc", "http://127.0.0.1:8731/callback")
        for frag in ("client_id=cid-123", "code_challenge=", "code_challenge_method=S256",
                     "state=st-abc", "response_type=code", "scope=internal"):
            self.assertIn(frag, u, frag)
        self.assertTrue(u.startswith("https://robinhood.com/oauth"))

    def test_never_puts_the_verifier_in_the_url(self):
        v = "verifier-x-long-enough-for-pkce-aaaaaaaaaaaaaaa"
        self.assertNotIn(v, rhauth.authorize_url("c", v, "s", "http://127.0.0.1:1/callback"))


class StateTest(unittest.TestCase):
    """CSRF: a callback whose state does not match ours is not ours."""

    def test_matching_state_accepted(self):
        self.assertTrue(rhauth.state_ok("abc123", "abc123"))

    def test_mismatched_state_rejected(self):
        self.assertFalse(rhauth.state_ok("abc123", "abc124"))

    def test_empty_state_rejected(self):
        self.assertFalse(rhauth.state_ok("", ""))
        self.assertFalse(rhauth.state_ok("abc", ""))


class TokenStoreTest(unittest.TestCase):
    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "token.json"

    def test_saved_token_is_owner_only(self):
        rhauth.save_token({"access_token": "secret", "refresh_token": "r"}, self.path)
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")

    def test_roundtrip(self):
        rhauth.save_token({"access_token": "a", "refresh_token": "r", "expires_at": 99}, self.path)
        self.assertEqual(rhauth.load_token(self.path)["refresh_token"], "r")

    def test_missing_token_is_none_not_crash(self):
        self.assertIsNone(rhauth.load_token(self.path))

    def test_corrupt_token_is_none_not_crash(self):
        self.path.write_text("{not json")
        self.assertIsNone(rhauth.load_token(self.path))

    def test_token_without_access_token_is_refused(self):
        with self.assertRaises(ValueError):
            rhauth.save_token({"refresh_token": "r"}, self.path)


class ExpiryTest(unittest.TestCase):
    def test_expired_token_needs_refresh(self):
        self.assertTrue(rhauth.needs_refresh({"expires_at": 100}, now=200))

    def test_token_inside_the_safety_margin_needs_refresh(self):
        self.assertTrue(rhauth.needs_refresh({"expires_at": 260}, now=200),
                        "refresh before it dies mid-order, not after")

    def test_fresh_token_does_not(self):
        self.assertFalse(rhauth.needs_refresh({"expires_at": 5000}, now=200))

    def test_token_with_no_expiry_is_treated_as_expired(self):
        self.assertTrue(rhauth.needs_refresh({}, now=200), "unknown expiry must fail closed")


class SafetyTest(unittest.TestCase):
    def test_no_order_placing_capability_exists_yet(self):
        """Switch 3 stays off: this module authenticates and reads. It cannot trade."""
        for forbidden in ("place_order", "submit_order", "buy", "sell"):
            self.assertFalse(hasattr(rhauth, forbidden), forbidden)

    def test_redirect_uri_is_loopback_only(self):
        self.assertTrue(rhauth.redirect_ok("http://127.0.0.1:8731/callback"))
        self.assertTrue(rhauth.redirect_ok("http://localhost:8731/callback"))
        self.assertFalse(rhauth.redirect_ok("https://evil.example.com/callback"))
        self.assertFalse(rhauth.redirect_ok("http://10.0.0.5:8731/callback"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
