"""Single-worker API entrypoint. Non-loopback listeners require a certificate."""
import argparse
import ipaddress
import ssl
from pathlib import Path

import uvicorn


def server_options(host: str, port: int, certfile: Path | None = None,
                   keyfile: Path | None = None):
    # Literal IP only: avoid hostname resolution changing the exposure boundary.
    address = ipaddress.ip_address(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if bool(certfile) != bool(keyfile):
        raise ValueError("Certificate and private key must be supplied together")
    if not address.is_loopback and certfile is None:
        raise ValueError("Non-loopback listeners require HTTPS certificate and private key")
    if certfile is not None:
        if not certfile.is_file() or not keyfile.is_file():
            raise ValueError("Certificate or private key file unavailable")
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            # Empty password avoids an interactive private-key prompt in a service.
            # For encrypted service keys, use a dedicated secret-management design.
            context.load_cert_chain(str(certfile), str(keyfile), password="")
        except (OSError, ValueError):
            raise ValueError("Certificate/private key validation failed") from None
    return {
        "app": "app.api.server:app", "host": str(address), "port": port,
        "workers": 1, "reload": False, "access_log": False, "proxy_headers": False,
        "server_header": False, "log_level": "warning", "limit_concurrency": 32,
        "timeout_keep_alive": 5, "timeout_graceful_shutdown": 160,
        "ssl_certfile": str(certfile) if certfile else None,
        "ssl_keyfile": str(keyfile) if keyfile else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--certfile", type=Path)
    parser.add_argument("--keyfile", type=Path)
    args = parser.parse_args()
    try:
        options = server_options(args.host, args.port, args.certfile, args.keyfile)
    except ValueError as exc:
        parser.error(str(exc))
    uvicorn.run(**options)


if __name__ == "__main__":
    main()
