"""飞书推送回归测试：环境代理绕过 + 失败可见性。"""

import logging

import feishu_notify


def test_post_bypasses_environment_proxy(monkeypatch):
    """_post 必须忽略环境代理；失效的 7892 代理会把推送静默吞掉。"""
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"code": 0}

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            seen["session"] = self

        def post(self, url, **kwargs):
            seen["url"] = url
            seen["kwargs"] = kwargs
            return FakeResponse()

    def fail_post(*args, **kwargs):
        raise AssertionError("_post 仍在直接使用 requests.post，未绕过环境代理")

    monkeypatch.setattr(feishu_notify.requests, "post", fail_post)
    monkeypatch.setattr(feishu_notify.requests, "Session", FakeSession)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7892")
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7892")

    assert feishu_notify._post({"msg_type": "text"}) is True
    assert seen.get("session") is not None
    assert seen["session"].trust_env is False
    assert "proxies" not in seen["kwargs"]


def test_send_b1_results_reports_failure(monkeypatch, caplog):
    """推送失败时返回 False 并记录 ERROR，不能静默当作成功。"""
    monkeypatch.setattr(feishu_notify, "send_feishu_text", lambda text: False)

    with caplog.at_level(logging.ERROR):
        result = feishu_notify.send_b1_results([])

    assert result is False
    assert "飞书推送失败" in caplog.text
