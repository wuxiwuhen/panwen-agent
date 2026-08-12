from panwen.data.ingest.checkpoint import Checkpoint

def test_mark_and_is_done(tmp_path):
    cp = Checkpoint(str(tmp_path / "cp.json"))
    assert not cp.is_done("daily_quote", "000001")
    cp.mark("daily_quote", "000001")
    assert cp.is_done("daily_quote", "000001")

def test_resume_iter_skips_done(tmp_path):
    cp = Checkpoint(str(tmp_path / "cp.json"))
    cp.mark("daily_quote", "000001")
    remaining = cp.resume_iter("daily_quote", ["000001", "000002"])
    assert remaining == ["000002"]

def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "cp.json")
    Checkpoint(p).mark("daily_quote", "000001")
    assert Checkpoint(p).is_done("daily_quote", "000001")
