# tests/data/test_client.py
import pandas as pd, pytest
from panwen.data.ingest import client

def test_fetch_returns_dataframe(mocker):
    mocker.patch.object(client, "_last_call_at", 0.0)
    fake = mocker.Mock(return_value=pd.DataFrame({"a": [1]}))
    df = client.fetch(fake, symbol="000001", min_interval=0)
    assert list(df["a"]) == [1]
    fake.assert_called_once_with(symbol="000001")

def test_fetch_retries_then_succeeds(mocker):
    mocker.patch.object(client, "_last_call_at", 0.0)
    mocker.patch("panwen.data.ingest.client.time.sleep")  # 加速
    flaky = mocker.Mock(side_effect=[RuntimeError("boom"), pd.DataFrame({"a": [2]})])
    df = client.fetch(flaky, min_interval=0, retries=3)
    assert list(df["a"]) == [2]
    assert flaky.call_count == 2

def test_fetch_gives_up_after_retries(mocker):
    mocker.patch.object(client, "_last_call_at", 0.0)
    mocker.patch("panwen.data.ingest.client.time.sleep")
    bad = mocker.Mock(side_effect=RuntimeError("always"))
    with pytest.raises(RuntimeError):
        client.fetch(bad, min_interval=0, retries=2)
    assert bad.call_count == 2  # 初试 + 1 次重试

def test_fetch_throttles_between_calls(mocker):
    sleeps = mocker.patch("panwen.data.ingest.client.time.sleep")
    mocker.patch.object(client, "_last_call_at", 0.0)
    fake = mocker.Mock(return_value=pd.DataFrame())
    client.fetch(fake, min_interval=0.5)
    client.fetch(fake, min_interval=0.5)
    assert any(s > 0 for s in [c.args[0] for c in sleeps.call_args_list])
