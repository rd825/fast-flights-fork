from typing import TypeVar, overload

from primp import Client

from .integrations.base import DataSourceIntegration, FetchIntegration
from .parser import ResultList, parse
from .querying import Query

URL = "https://www.google.com/travel/flights"


T = TypeVar("T")


@overload
def get_flights(
    q: Query | str, /, *, proxy: str | None = None, integration: None = None
) -> ResultList: ...


@overload
def get_flights(
    q: Query | str, /, *, proxy: str | None = None, integration: FetchIntegration
) -> ResultList: ...


@overload
def get_flights(
    q: Query | str,
    /,
    *,
    proxy: str | None = None,
    integration: DataSourceIntegration[T],
) -> T: ...


def get_flights(
    q: Query | str,
    /,
    *,
    proxy: str | None = None,
    integration: FetchIntegration | DataSourceIntegration[T] | None = None,
) -> T | ResultList:
    """Get flights.

    Args:
        q: The query.
        proxy (optional): Proxy, if you're using `fast-flight`'s default fetcher.
        integration (optional): Plug-in integration.
    """
    if integration is not None and isinstance(integration, DataSourceIntegration):
        return integration.fetch(q)

    html = fetch_flights_html(q, proxy=proxy, fetch_integration=integration)
    return parse(html)


def get_flights_from_tfs(
    tfs: str,
    /,
    *,
    language: str = "",
    currency: str = "",
    proxy: str | None = None,
    page: str = "flights",
) -> ResultList:
    """Fetch + parse a pre-encoded ``tfs`` (url-safe base64) directly.

    Unlike ``get_flights(str)``, which treats a bare string as a natural-
    language ``q=`` query, this sends the string as the ``tfs`` parameter —
    for callers that build their own protobuf beyond what ``create_query``
    supports (e.g. a pinned-outbound round trip, whose ``page="booking"``
    response lists the RETURN options priced at the combined fare).

    Args:
        tfs: The raw tfs value.
        language / currency: ``hl`` / ``curr`` params ("" lets Google decide).
        proxy: Optional proxy.
        page: "flights" (default), "search", or "booking" — which
            /travel/flights page to request.
    """
    suffix = {"flights": "", "search": "/search", "booking": "/booking"}[page]
    client = Client(
        impersonate="chrome_145",
        impersonate_os="macos",
        referer=True,
        proxy=proxy,
        cookie_store=True,
    )
    res = client.get(URL + suffix, params={"tfs": tfs, "hl": language, "curr": currency})
    return parse(res.text)


def fetch_flights_html(
    q: Query | str,
    /,
    *,
    proxy: str | None = None,
    fetch_integration: FetchIntegration | None = None,
) -> str:
    """Fetch flights and get the **HTML**.

    Args:
        q: The query.
        proxy (str, optional): Proxy.
    """
    if fetch_integration is None:
        client = Client(
            impersonate="chrome_145",
            impersonate_os="macos",
            referer=True,
            proxy=proxy,
            cookie_store=True,
        )

        if isinstance(q, Query):
            params = q.params()

        else:
            params = {"q": q}

        res = client.get(URL, params=params)
        return res.text

    else:
        return fetch_integration.fetch_html(q)
