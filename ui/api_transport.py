"""HTTPS-only debug client. No local database or model access."""
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class ApiError(RuntimeError):
    def __init__(self, status=0):
        self.status = status
        super().__init__("API request failed")


def validate_server(server):
    value = urlsplit(server)
    if (value.scheme != "https" or not value.hostname or value.username or value.password
            or value.path not in ("", "/") or value.query or value.fragment):
        raise ApiError()
    return server.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError(code)


def call_api(server, method, segments, *, token=None, payload=None, query=None,
             raw=None, content_type=None):
    server = validate_server(server)
    url = server + "/api/v1/" + "/".join(quote(part, safe="") for part in segments)
    if query:
        url += "?" + urlencode(query)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if raw is not None:
        if payload is not None or content_type not in ("text/plain", "application/pdf"):
            raise ApiError()
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise ApiError(413)
        data = raw
        headers["Content-Type"] = content_type
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    try:
        request = Request(url, data=data, headers=headers, method=method)
        context = ssl.create_default_context(cafile=os.getenv("MAINTENANCE_CA_FILE") or None)
        with build_opener(NoRedirect(), HTTPSHandler(context=context)).open(request, timeout=150) as response:
            raw = response.read(2097153)
        if len(raw) > 2097152:
            raise ApiError()
        return json.loads(raw)
    except HTTPError as exc:
        raise ApiError(exc.code) from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise ApiError() from None
