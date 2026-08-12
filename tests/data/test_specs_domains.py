from panwen.data.ingest import specs


def test_domain_specs_cover_all():
    tables = {s.table for s in specs.build_domain_specs()}
    assert {"industry_board", "industry_board_const", "industry_board_daily",
            "concept_board", "concept_board_const", "margin_daily",
            "dragon_tiger", "top10_holders", "macro_series"} <= tables


def test_margin_spec_iteration():
    m = [s for s in specs.build_domain_specs() if s.table == "margin_daily"][0]
    assert m.iteration == "oneshot"
