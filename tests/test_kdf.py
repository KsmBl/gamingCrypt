import base64

import pytest

from gamingcrypt.unlock import kdf

FAST = {"algorithm": "scrypt", "salt": "00112233445566778899aabbccddeeff", "n": 1024, "r": 8, "p": 1}


def test_no_params_is_identity():
    assert kdf.derive_password("1234", None) == "1234"
    assert kdf.derive_password("1234", {}) == "1234"


def test_derivation_is_deterministic_and_fits_veracrypt():
    a = kdf.derive_password("1234", FAST)
    assert a == kdf.derive_password("1234", FAST)
    assert a != "1234" and len(a) == 43 and len(a) <= 64
    assert len(base64.urlsafe_b64decode(a + "=")) == 32
    assert a.isascii()


def test_salt_and_secret_change_the_result():
    other_salt = dict(FAST, salt="ff" * 16)
    assert kdf.derive_password("1234", FAST) != kdf.derive_password("1234", other_salt)
    assert kdf.derive_password("1234", FAST) != kdf.derive_password("1235", FAST)


def test_known_vector():
    # RFC 7914 style check against hashlib directly
    import hashlib

    raw = hashlib.scrypt(b"1-7-13-25", salt=bytes.fromhex(FAST["salt"]), n=1024, r=8, p=1, dklen=32)
    assert kdf.derive_password("1-7-13-25", FAST) == base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_new_params_random_salt_and_defaults():
    a, b = kdf.new_params(), kdf.new_params()
    assert a["salt"] != b["salt"] and len(bytes.fromhex(a["salt"])) == 16
    assert a["algorithm"] == "scrypt" and a["n"] == 2**18 and a["r"] == 8
    assert kdf.new_params(rng=lambda n: b"\x01" * n)["salt"] == "01" * 16


@pytest.mark.parametrize("params", [
    dict(FAST, algorithm="md5"),
    dict(FAST, salt="zz"),
    dict(FAST, salt="00"),
    {"algorithm": "scrypt"},
])
def test_bad_params(params):
    with pytest.raises(kdf.KDFError):
        kdf.derive_password("x", params)


def test_describe():
    assert "legacy" in kdf.describe(None)
    assert kdf.describe(kdf.new_params()) == "scrypt (N=2^18, 256 MB)"
