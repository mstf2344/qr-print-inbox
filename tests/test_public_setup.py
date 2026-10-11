import json

import pytest

from scripts import setup_public


def test_independent_setup_reuses_secret_and_never_changes_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_public, "ROOT", tmp_path)
    original_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    originals = {}
    for folder in ("worker", "legacy-worker"):
        target = tmp_path / folder / "wrangler.jsonc"
        target.parent.mkdir()
        originals[folder] = (original_root / folder / "wrangler.jsonc").read_text()
        target.write_text(originals[folder])
    params = ("https://my-shop.example.com", "my-shop", "my-relay")
    connection, secret = setup_public.prepare(*params)
    assert len(secret) >= 32
    assert setup_public.prepare(*params) == (connection, secret)
    assert json.loads(connection.read_text())["relay_url"] == params[0] + "/desktop"
    for folder in originals:
        assert (tmp_path / folder / "wrangler.jsonc").read_text() == originals[folder]
        config = json.loads((tmp_path / folder / "wrangler.local.jsonc").read_text())
        assert secret not in json.dumps(config)
    gateway = json.loads((tmp_path / "worker/wrangler.local.jsonc").read_text())
    assert gateway["services"][0]["service"] == "my-relay"
    with pytest.raises(ValueError):
        setup_public.prepare("https://other.example.com", "my-shop", "my-relay")
    assert json.loads(connection.read_text())["gateway_secret"] == secret


@pytest.mark.parametrize("url", [
    "http://shop.example.com", "https://user:pass@shop.example.com",
    "https://shop.example.com/wrong", "https://shop.example.com?key=abc",
])
def test_setup_rejects_bad_origins(url):
    with pytest.raises(ValueError):
        setup_public.prepare(url, "my-shop", "my-relay")
