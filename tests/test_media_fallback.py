"""The two-strategy media hosting chain. All transports stubbed; no network."""
import pytest

from agents import publisher


@pytest.fixture()
def img(tmp_path):
    from PIL import Image
    p = tmp_path / "card.png"
    Image.new("RGB", (20, 20), "red").save(p)
    return str(p)


def test_public_urls_pass_straight_through(img):
    url, strategy = publisher._public_media_url("https://example.com/a.png")
    assert (url, strategy) == ("https://example.com/a.png", "already-public")


def test_strategy_one_used_when_available(img, monkeypatch):
    monkeypatch.setattr(publisher, "_ayrshare_upload",
                        lambda p: "https://media.ayrshare.com/x.png")
    monkeypatch.setattr(publisher, "_anon_upload",
                        lambda p: pytest.fail("fallback must not run"))
    url, strategy = publisher._public_media_url(img)
    assert strategy == "ayrshare"
    assert url.startswith("https://media.ayrshare.com/")


@pytest.mark.parametrize("code", [401, 402, 403])
def test_plan_block_falls_back_instead_of_failing(img, monkeypatch, code, capsys):
    def blocked(path):
        raise publisher.MediaUploadBlocked(f"HTTP {code} from /media/uploadUrl")
    monkeypatch.setattr(publisher, "_ayrshare_upload", blocked)
    monkeypatch.setattr(publisher, "_anon_upload",
                        lambda p: "https://files.catbox.moe/abc123.png")

    url, strategy = publisher._public_media_url(img)
    assert strategy == publisher.FALLBACK_HOST
    assert url == "https://files.catbox.moe/abc123.png"
    assert "strategy 1" in capsys.readouterr().out


def test_other_ayrshare_error_also_falls_back(img, monkeypatch):
    monkeypatch.setattr(publisher, "_ayrshare_upload",
                        lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(publisher, "_anon_upload",
                        lambda p: "https://files.catbox.moe/def456.png")
    _url, strategy = publisher._public_media_url(img)
    assert strategy == publisher.FALLBACK_HOST


def test_both_failing_names_the_plan_block(img, monkeypatch):
    monkeypatch.setattr(publisher, "_ayrshare_upload",
                        lambda p: (_ for _ in ()).throw(
                            publisher.MediaUploadBlocked("HTTP 403 from /media/uploadUrl")))
    monkeypatch.setattr(publisher, "_anon_upload",
                        lambda p: (_ for _ in ()).throw(RuntimeError("host down")))
    with pytest.raises(publisher.ValidationError) as err:
        publisher._public_media_url(img)
    msg = str(err.value)
    assert "not permitted on this plan" in msg
    assert publisher.FALLBACK_HOST in msg
    assert "host down" in msg


def test_both_failing_distinguishes_a_non_plan_error(img, monkeypatch):
    monkeypatch.setattr(publisher, "_ayrshare_upload",
                        lambda p: (_ for _ in ()).throw(RuntimeError("timeout")))
    monkeypatch.setattr(publisher, "_anon_upload",
                        lambda p: (_ for _ in ()).throw(RuntimeError("host down")))
    with pytest.raises(publisher.ValidationError) as err:
        publisher._public_media_url(img)
    msg = str(err.value)
    assert "not permitted on this plan" not in msg
    assert "timeout" in msg


def test_anon_upload_rejects_a_non_url_response(img, monkeypatch):
    class R:
        text = "something went wrong"
        def raise_for_status(self): pass
    monkeypatch.setattr("requests.post", lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="unexpected response"):
        publisher._anon_upload(img)


def test_api_key_never_reaches_the_fallback_host(img, monkeypatch):
    """The anonymous host must not receive our Ayrshare credentials."""
    monkeypatch.setenv("AYRSHARE_API_KEY", "secret-key-value")
    seen = {}

    class R:
        text = "https://files.catbox.moe/ok.png"
        def raise_for_status(self): pass

    def fake_post(url, data=None, files=None, headers=None, timeout=None):
        seen["headers"] = headers or {}
        seen["data"] = data or {}
        return R()

    monkeypatch.setattr("requests.post", fake_post)
    publisher._anon_upload(img)
    blob = repr(seen)
    assert "secret-key-value" not in blob
    assert "Authorization" not in seen["headers"]
