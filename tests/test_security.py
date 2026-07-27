from security import hash_secret, normalize_email, verify_secret


def test_email_normalization():
    assert normalize_email(" User@IITI.AC.IN ") == "user@iiti.ac.in"


def test_secret_hash_is_not_recoverable_plaintext():
    digest = hash_secret("123456")
    assert digest != "123456"
    assert verify_secret("123456", digest)
    assert not verify_secret("654321", digest)
