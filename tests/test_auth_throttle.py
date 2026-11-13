import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


@unittest.skipUnless(importlib.util.find_spec("argon2"), "install server dependencies")
class LoginThrottleTests(unittest.TestCase):
    def test_repeated_failures_for_one_account_are_rate_limited(self):
        from packages.runtime.auth import AccessError, AuthStore

        with TemporaryDirectory() as directory:
            auth = AuthStore(Path(directory) / "auth.sqlite3")
            for _ in range(8):
                with self.assertRaises(AccessError) as error:
                    auth.login("unknown-user", "wrong-password", 8)
                self.assertEqual(error.exception.status, 401)
            with self.assertRaises(AccessError) as error:
                auth.login("unknown-user", "wrong-password", 8)
            self.assertEqual(error.exception.status, 429)


if __name__ == "__main__":
    unittest.main()
