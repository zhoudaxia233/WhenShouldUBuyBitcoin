from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dca_service.services import fx_rates


@pytest.fixture(autouse=True)
def empty_cache():
    fx_rates._settled.clear()


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_weekend_buy_uses_the_reference_date_returned():
    payload = {"amount": 1.0, "base": "EUR", "date": "2025-11-14", "rates": {"USD": 1.1648}}
    with patch.object(fx_rates.httpx, "get", return_value=_response(payload)) as get:
        rate = fx_rates.eur_usd_rate(date(2025, 11, 15))

    assert rate == fx_rates.FxRate(rate=1.1648, date="2025-11-14")
    assert get.call_args.args[0].endswith("/2025-11-15")
    assert get.call_args.kwargs["params"] == {"base": "EUR", "symbols": "USD"}


def test_past_rates_are_fetched_once():
    payload = {"date": "2025-11-12", "rates": {"USD": 1.1612}}
    with patch.object(fx_rates.httpx, "get", return_value=_response(payload)) as get:
        fx_rates.eur_usd_rate(date(2025, 11, 12))
        fx_rates.eur_usd_rate(date(2025, 11, 12))

    assert get.call_count == 1


@pytest.mark.parametrize(
    "side_effect,payload",
    [
        (httpx.ConnectError("down"), None),
        (None, {"date": "2025-11-12", "rates": {}}),
        (None, {"date": "2025-11-12", "rates": {"USD": 0}}),
    ],
)
def test_failures_raise_fx_unavailable(side_effect, payload):
    kwargs = {"side_effect": side_effect} if side_effect else {"return_value": _response(payload)}
    with patch.object(fx_rates.httpx, "get", **kwargs):
        with pytest.raises(fx_rates.FxUnavailable):
            fx_rates.eur_usd_rate(date(2025, 11, 12))
