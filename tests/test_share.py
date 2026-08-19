from dataclasses import replace

import pytest

import share


def test_share_rejects_lab_mode(monkeypatch):
    monkeypatch.setattr(share, "settings", replace(share.settings, mode="lab"))
    with pytest.raises(SystemExit, match="Personal"):
        share.create_claim("alice")


def test_share_rejects_invalid_handle(monkeypatch):
    monkeypatch.setattr(share, "settings", replace(share.settings, mode="personal"))
    with pytest.raises(SystemExit, match="Handle"):
        share.create_claim("Alice Smith")
