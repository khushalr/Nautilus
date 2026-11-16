import json
import zlib
from decimal import Decimal
import pytest
from app.microstructure.book import Book, InvalidBook, decode
from app.microstructure.replay import replay


def snapshot():
    return {"type": "snapshot", "product_id": "BTC-USD",
            "bids": [["100", "2"], ["99", "4"]], "asks": [["102", "1"]]}


def test_decimal_decoder():
    assert decode('{"price": 0.10000000}')["price"].as_tuple().exponent == -8


def test_features_and_delete():
    b = Book("coinbase")
    b.apply(snapshot(), 10)
    f = b.features(10)
    assert Decimal(f["spread"]) == 2
    assert Decimal(f["microprice"]) == Decimal(304)/3
    b.apply({"type": "l2update", "product_id": "BTC-USD",
             "changes": [["buy", "100", "0"]]}, 11)
    assert Decimal(b.features(11)["ofi"]) == -2


@pytest.mark.parametrize("changes", [
    [["buy", "103", "1"]], [["buy", "100", "-1"]],
    [["sell", "102", "0"]], [["wrong", "100", "1"]],
    [["buy", "NaN", "1"]]
])
def test_invalid_update_fails_closed(changes):
    b = Book("coinbase")
    b.apply(snapshot(), 10)
    with pytest.raises(InvalidBook):
        b.apply({"type": "l2update", "product_id": "BTC-USD", "changes": changes}, 11)
    assert not b.ready
    with pytest.raises(InvalidBook):
        b.features(12)


def test_snapshot_required_and_stale():
    b = Book("coinbase")
    with pytest.raises(InvalidBook):
        b.apply({"type": "l2update", "product_id": "BTC-USD", "changes": []}, 1)
    b.apply(snapshot(), 10)
    with pytest.raises(InvalidBook):
        b.features(6_000_000_010)


def test_kraken_crc_and_recovery():
    b = Book("kraken")
    m = {"channel": "book", "type": "snapshot", "data": [{
        "symbol": "BTC/USD", "bids": [{"price": "100.0", "qty": "2.00"}],
        "asks": [{"price": "102.0", "qty": "1.00"}],
        "checksum": zlib.crc32(b"10201001000200")}]}
    b.apply(m, 10)
    assert b.ready
    m["data"][0]["checksum"] = 0
    with pytest.raises(InvalidBook):
        b.apply(m, 11)
    assert not b.ready


def test_replay_determinism_and_sessions():
    line = json.dumps({"received_ns": 10, "raw": json.dumps(snapshot())})
    a, b = replay([line], "coinbase"), replay([line], "coinbase")
    assert a["feature_sha256"] == b["feature_sha256"]
    assert a["book_events"] == 1
    with pytest.raises(ValueError):
        replay([line, json.dumps({"received_ns": 9, "raw": "{}"})], "coinbase")

def test_normalized_benchmark_hand_calculated():
    from app.microstructure.benchmark import python_book
    result = python_book([(0, 100001, 2), (0, 100001, 0)])
    assert result["checksum"] == 400201
    assert result["events"] == 2
