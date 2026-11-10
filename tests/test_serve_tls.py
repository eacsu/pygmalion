"""检查单端口 HTTP/HTTPS 的启动选项，不启动服务或连接硬件。"""

import uvicorn
from typer.testing import CliRunner

from pygmalion.commands.app import app


def test_serve_selects_http_or_https(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--port", "18080"])
    assert result.exit_code == 0
    assert calls[-1]["ssl_certfile"] is None
    assert calls[-1]["ssl_keyfile"] is None
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("certificate")
    key.write_text("key")
    result = runner.invoke(
        app, ["serve", "--tls-cert", str(cert), "--tls-key", str(key)]
    )
    assert result.exit_code == 0
    assert calls[-1]["ssl_certfile"] == str(cert)
    assert calls[-1]["ssl_keyfile"] == str(key)
    assert runner.invoke(app, ["serve", "--tls-cert", str(cert)]).exit_code != 0
    assert (
        runner.invoke(
            app,
            ["serve", "--tls-cert", str(cert), "--tls-key", str(tmp_path / "missing")],
        ).exit_code
        != 0
    )
