"""Тесты безопасности обновлений: подпись Ed25519 (RFC 8032), манифест релиза.

Запуск: python tools/security/test_updates_security.py
"""
import json
import sys
import tempfile
import unittest
import unittest.mock as mock
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import update_verify as uv  # noqa: E402
from core import updater as up  # noqa: E402
from core import updates as ups  # noqa: E402
from core.config import VERSION  # noqa: E402
from server import server as srv  # noqa: E402

# RFC 8032, раздел 7.1 — эталонные векторы Ed25519.
V1_SK = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
V1_PK = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
V1_SIG = ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
          "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
V2_SK = "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
V2_PK = "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
V2_MSG = bytes.fromhex("72")
V2_SIG = ("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
          "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")


class TestRfc8032Vectors(unittest.TestCase):
    """Реализация обязана совпадать с эталонными векторами RFC."""

    def test_vector1_public_key(self):
        self.assertEqual(uv.public_key_from_secret(V1_SK), V1_PK)

    def test_vector1_signature(self):
        self.assertEqual(uv.sign(b"", V1_SK), V1_SIG)

    def test_vector1_verify(self):
        self.assertTrue(uv.verify(b"", V1_SIG, V1_PK))

    def test_vector2_one_byte_message(self):
        self.assertEqual(uv.public_key_from_secret(V2_SK), V2_PK)
        self.assertEqual(uv.sign(V2_MSG, V2_SK), V2_SIG)
        self.assertTrue(uv.verify(V2_MSG, V2_SIG, V2_PK))


class TestVerifyGuards(unittest.TestCase):
    def test_tampered_message_rejected(self):
        self.assertFalse(uv.verify(b"x", V1_SIG, V1_PK))

    def test_wrong_key_rejected(self):
        self.assertFalse(uv.verify(b"", V1_SIG, V2_PK))

    def test_truncated_signature_rejected(self):
        self.assertFalse(uv.verify(b"", V1_SIG[:40], V1_PK))

    def test_garbage_rejected_without_exception(self):
        self.assertFalse(uv.verify(b"", "not-a-signature", V1_PK))
        self.assertFalse(uv.verify(b"", V1_SIG, "not-a-key"))

    def test_unset_production_key_fails_closed(self):
        # Пока ключ не вшит, проверок нет: verify обязан вернуть False,
        # а не «пропустить» (fail-closed).
        self.assertEqual(uv.PUBKEY, "")
        self.assertFalse(uv.verify(b"", V1_SIG, None))
        self.assertFalse(uv.verify(b"", V1_SIG, ""))

    def test_base64_signature_roundtrip(self):
        import base64
        sig_b64 = base64.b64encode(bytes.fromhex(V1_SIG)).decode("ascii")
        self.assertTrue(uv.verify(b"", sig_b64, V1_PK))

    def test_keygen_roundtrip(self):
        sk, pk = uv.keygen()
        sig = uv.sign(b"manifest-bytes", sk)
        self.assertTrue(uv.verify(b"manifest-bytes", sig, pk))
        self.assertFalse(uv.verify(b"manifest-byte5", sig, pk))

    def test_fingerprint_stable_and_distinct(self):
        fp1 = uv.pubkey_fingerprint(V1_PK)
        self.assertEqual(fp1, uv.pubkey_fingerprint(V1_PK))
        self.assertEqual(len(fp1), 12)
        self.assertNotEqual(fp1, uv.pubkey_fingerprint(V2_PK))
        self.assertEqual(uv.pubkey_fingerprint(""), "")


def _manifest(**overrides):
    base = {
        "version": "0.9",
        "tag": "Pre-Release-0.9",
        "artifacts": {
            "exe": {"file": "Zapret2GUI.zip", "sha256": "a" * 64},
            "portable": {"file": "Zapret2GUI-portable.zip",
                         "sha256": "b" * 64},
            "lite": {"file": "Zapret2GUI-lite.zip", "sha256": "c" * 64},
        },
    }
    for key, value in overrides.items():
        if key == "artifacts":
            base["artifacts"] = value
        else:
            base[key] = value
    return base


class TestReleaseManifest(unittest.TestCase):
    """Манифест релиза: тег, анти-даунгрейд, артефакты, корректность sha."""

    def test_valid_manifest_accepted(self):
        self.assertIsNone(up.validate_release(
            _manifest(), "Pre-Release-0.9", "0.8", "exe"))

    def test_tag_mismatch_rejected(self):
        err = up.validate_release(_manifest(), "Pre-Release-0.8", "0.8", "exe")
        self.assertIn("релиз", err or "")

    def test_downgrade_rejected(self):
        err = up.validate_release(_manifest(version="0.8"),
                                  "Pre-Release-0.9", "0.9", "exe")
        self.assertIn("новее", err or "")

    def test_same_version_rejected(self):
        err = up.validate_release(_manifest(version="0.9"),
                                  "Pre-Release-0.9", "0.9", "exe")
        self.assertIn("новее", err or "")

    def test_missing_artifact_rejected(self):
        m = _manifest(artifacts={"exe": {"file": "x.zip", "sha256": "a" * 64}})
        err = up.validate_release(m, "Pre-Release-0.9", "0.8", "portable")
        self.assertIn("артефакт", err or "")

    def test_bad_sha_rejected(self):
        m = _manifest(artifacts={"exe": {"file": "x.zip", "sha256": "zz"}})
        err = up.validate_release(m, "Pre-Release-0.9", "0.8", "exe")
        self.assertIn("сумма", err or "")

    def test_non_dict_rejected(self):
        self.assertIsNotNone(up.validate_release([], "Pre-Release-0.9",
                                                 "0.8", "exe"))

    def test_fetch_update_refuses_without_hash(self):
        # Без подтверждённой контрольной суммы сеть не трогаем вообще.
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                up.fetch_update("exe", "Pre-Release-0.9", Path(td),
                                sha256_expected=None)


class TestVersionSources(unittest.TestCase):
    """Сверка независимых источников версии (raw/API)."""

    def test_agree(self):
        self.assertEqual(ups.merge_version_sources("Pre-Release 0.9",
                                                   "Pre-Release 0.9"),
                         ("Pre-Release 0.9", None))

    def test_disagree_rejects(self):
        latest, err = ups.merge_version_sources("Pre-Release 0.9",
                                                "Pre-Release 0.8")
        self.assertIsNone(latest)
        self.assertIsNotNone(err)

    def test_single_source_ok(self):
        self.assertEqual(ups.merge_version_sources("Pre-Release 0.9", None),
                         ("Pre-Release 0.9", None))
        self.assertEqual(ups.merge_version_sources(None, "Pre-Release 0.9"),
                         ("Pre-Release 0.9", None))

    def test_both_missing(self):
        latest, err = ups.merge_version_sources(None, None)
        self.assertIsNone(latest)
        self.assertIsNotNone(err)


def _make_dist_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("core/marker.txt", "ok")
        zf.writestr("update_manifest.json", "{}")


class TestUpdateWorkerSignature(unittest.TestCase):
    """Worker обязан ставить только обновления с валидной подписью."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        srv.init(self.root)
        self.sk, self.pk = uv.keygen()
        major, minor = ups.version_key(VERSION)[:2]
        self.new_version = f"{major}.{minor + 1}"
        self.tag = ups.tag_from_version(self.new_version)

    def tearDown(self):
        self.td.cleanup()

    def _signed(self, version=None):
        m = _manifest(version=version or self.new_version, tag=self.tag)
        raw = json.dumps(m).encode()
        return raw, uv.sign(raw, self.sk)

    def _run(self, manifest_bytes, sig, pubkey=""):
        zip_path = self.root / "update_portable.zip"
        _make_dist_zip(zip_path)
        with mock.patch.object(uv, "PUBKEY", pubkey), \
                mock.patch.object(up, "fetch_release_manifest",
                                  return_value=(manifest_bytes, sig)), \
                mock.patch.object(up, "fetch_update",
                                  return_value=zip_path), \
                mock.patch("core.service_manager.is_installed",
                           return_value=False):
            srv._run_update_worker("portable", self.tag,
                                   {"tag": self.tag,
                                    "latest": self.new_version})
        return dict(srv._updater_state)

    def test_signed_update_applied(self):
        raw, sig = self._signed()
        state = self._run(raw, sig, self.pk)
        self.assertIsNone(state["error"])
        self.assertTrue((state.get("result") or {}).get("signature_verified"))

    def test_tampered_manifest_rejected(self):
        raw, sig = self._signed()
        bad = raw.replace(b'"version": "' + self.new_version.encode() + b'"',
                          b'"version": "99.99"')
        state = self._run(bad, sig, self.pk)
        self.assertIn("подлинност", state["error"] or "")

    def test_unset_pubkey_rejected(self):
        raw, sig = self._signed()
        state = self._run(raw, sig, "")
        self.assertIn("подлинност", state["error"] or "")

    def test_downgrade_rejected(self):
        raw, sig = self._signed(version=VERSION)
        state = self._run(raw, sig, self.pk)
        self.assertIn("новее", state["error"] or "")

    def test_state_reset_between_runs(self):
        # После неудачного прогона следующий (успешный) не должен оставлять
        # чужой error/result в состоянии апдейтера.
        raw, sig = self._signed(version=VERSION)
        self._run(raw, sig, self.pk)
        raw, sig = self._signed()
        state = self._run(raw, sig, self.pk)
        self.assertIsNone(state["error"])
        self.assertTrue((state.get("result") or {}).get("signature_verified"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
