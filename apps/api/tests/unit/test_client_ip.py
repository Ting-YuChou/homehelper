"""The caller's IP for rate limits (ADR-011). Browsers reach the API through the web app's
`/v1` proxy, which forwards the visitor's address with a shared secret; direct callers on
Cloud Run are identified by the address Cloud Run appended to X-Forwarded-For."""

from starlette.requests import Request

from homehelper.api.deps import client_ip
from tests.conftest import make_settings

SECRET = "proxy-secret"


def _request(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    }
    return Request(scope)


def test_locally_the_socket_peer_is_the_client() -> None:
    settings = make_settings()
    request = _request({"X-Forwarded-For": "6.6.6.6"}, peer="127.0.0.1")
    assert client_ip(request, settings) == "127.0.0.1"


def test_on_cloud_run_the_last_forwarded_address_is_the_client() -> None:
    settings = make_settings(app_env="production", proxy_secret=SECRET)
    # The first entry is whatever the caller sent; Cloud Run appended the real address.
    request = _request({"X-Forwarded-For": "6.6.6.6, 203.0.113.7"})
    assert client_ip(request, settings) == "203.0.113.7"
    assert client_ip(_request({}), settings) == "10.0.0.9"


def test_the_web_proxy_vouches_for_the_visitor_with_the_shared_secret() -> None:
    settings = make_settings(app_env="production", proxy_secret=SECRET)
    proxied = {
        "X-HH-Client-IP": "198.51.100.4",
        "X-HH-Proxy-Secret": SECRET,
        "X-Forwarded-For": "198.51.100.4, 35.0.0.1",  # 35.0.0.1: the web service's egress
    }
    assert client_ip(_request(proxied), settings) == "198.51.100.4"


def test_a_forged_client_ip_header_is_ignored() -> None:
    settings = make_settings(app_env="production", proxy_secret=SECRET)
    wrong = {
        "X-HH-Client-IP": "1.1.1.1",
        "X-HH-Proxy-Secret": "guess",
        "X-Forwarded-For": "9.9.9.9",
    }
    assert client_ip(_request(wrong), settings) == "9.9.9.9"
    no_secret_configured = make_settings(app_env="production")
    forged = {"X-HH-Client-IP": "1.1.1.1", "X-HH-Proxy-Secret": "", "X-Forwarded-For": "9.9.9.9"}
    assert client_ip(_request(forged), no_secret_configured) == "9.9.9.9"
