from pathlib import Path

import pytest

from scripts.serve_api import server_options


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "10.0.0.5"])
def test_non_loopback_requires_tls(host):
    with pytest.raises(ValueError, match="HTTPS"):
        server_options(host, 8000)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_local_entrypoint_keeps_single_worker_and_no_access_log(host):
    options = server_options(host, 8000)
    assert options["workers"] == 1 and options["reload"] is False
    assert options["access_log"] is False and options["proxy_headers"] is False
    assert options["ssl_certfile"] is None


def test_invalid_port_hostname_and_partial_tls_rejected():
    for port in (0, 65536, True):
        with pytest.raises(ValueError):
            server_options("127.0.0.1", port)
    with pytest.raises(ValueError):
        server_options("localhost", 8000)
    with pytest.raises(ValueError, match="together"):
        server_options("127.0.0.1", 8000, Path("certificate.pem"))


def test_invalid_certificate_cannot_start_listener(tmp_path):
    certificate = tmp_path / "certificate.pem"
    key = tmp_path / "key.pem"
    certificate.write_text("invalid-certificate", encoding="utf-8")
    key.write_text("SIMULATED_PRIVATE_KEY_MUST_NOT_ECHO", encoding="utf-8")
    with pytest.raises(ValueError, match="validation failed") as caught:
        server_options("0.0.0.0", 8443, certificate, key)
    assert "SIMULATED_PRIVATE_KEY" not in str(caught.value)
