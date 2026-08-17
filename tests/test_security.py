import pytest

from security import (
    InvalidSshPublicKey,
    hash_secret,
    normalize_email,
    parse_ssh_public_key,
    ssh_key_public_view,
    ssh_public_key_fingerprint,
    verify_secret,
)


def test_email_normalization():
    assert normalize_email(" User@IITI.AC.IN ") == "user@iiti.ac.in"


def test_secret_hash_is_not_recoverable_plaintext():
    digest = hash_secret("123456")
    assert digest != "123456"
    assert verify_secret("123456", digest)
    assert not verify_secret("654321", digest)


def _ed25519(comment="laptop"):
    import base64
    import struct
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + bytes(range(32))
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"


def test_ssh_public_key_is_canonicalized_and_fingerprinted():
    raw = "  " + _ed25519("laptop extra") + "\n"
    canonical = parse_ssh_public_key(raw)
    assert canonical == _ed25519("laptop extra").strip()
    fingerprint = ssh_public_key_fingerprint(canonical)
    assert fingerprint.startswith("SHA256:")
    assert fingerprint == ssh_public_key_fingerprint(canonical)
    assert ssh_key_public_view(canonical) == {
        "fingerprint": fingerprint,
        "comment": "laptop extra",
    }


def test_ssh_public_key_rejects_invalid_shapes():
    valid = _ed25519()
    with pytest.raises(InvalidSshPublicKey, match="required"):
        parse_ssh_public_key("  ")
    with pytest.raises(InvalidSshPublicKey, match="Private keys"):
        parse_ssh_public_key("-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n")
    with pytest.raises(InvalidSshPublicKey, match="single line"):
        parse_ssh_public_key(valid + "\nssh-ed25519 AAAA")
    with pytest.raises(InvalidSshPublicKey, match="Unsupported"):
        parse_ssh_public_key('command="id" ' + valid)
    with pytest.raises(InvalidSshPublicKey, match="Unsupported"):
        parse_ssh_public_key("ssh-dss AAAA comment")
    with pytest.raises(InvalidSshPublicKey, match="invalid"):
        parse_ssh_public_key("ssh-ed25519 !!!")
    with pytest.raises(InvalidSshPublicKey, match="too large"):
        parse_ssh_public_key("ssh-ed25519 " + ("A" * 9000))


def test_ssh_key_public_view_hides_missing_keys():
    assert ssh_key_public_view(None) is None
    assert ssh_key_public_view("") is None


def test_ssh_public_key_accepts_ssh_keygen_ed25519(tmp_path):
    import shutil
    import subprocess

    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is not installed")
    key_path = tmp_path / "dummy"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "dummy@opengpu", "-f", str(key_path)],
        check=True,
        capture_output=True,
    )
    canonical = parse_ssh_public_key((tmp_path / "dummy.pub").read_text())
    assert canonical.startswith("ssh-ed25519 ")
    assert canonical.endswith(" dummy@opengpu")
    view = ssh_key_public_view(canonical)
    assert view["fingerprint"].startswith("SHA256:")
    assert view["comment"] == "dummy@opengpu"
