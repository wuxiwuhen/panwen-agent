"""T3: Lambda-source 回归保护。

spec.source 必须用 lambda 包裹(在调用时经 akshare 模块属性解析),这样测试里的
mocker.patch("akshare.<fn>") 才生效;若任一 spec 被回退成直接引用 ak.<fn>,
import 时即固化函数对象、绕过 mock -> 大量 mock 测试静默失效(假绿)。
本文件遍历全部 spec 构建器,断言每个 source 都是 lambda(<lambda>),任一回退即红。
"""
import pytest

from panwen.data.ingest import specs


@pytest.mark.parametrize("builder", [
    specs.build_quote_specs,
    specs.build_finance_specs,
    specs.build_domain_specs,
])
def test_every_spec_source_is_lambda(builder):
    for spec in builder():
        assert spec.source.__name__ == "<lambda>", (
            f"{spec.name}.source 必须是 lambda 以兼容 mocker.patch(\"akshare.<fn>\"); "
            f"当前为 {spec.source.__name__}({spec.source!r}) -> 直接引用会在 import 时固化,"
            f"绕过 mock。改回 source=lambda *a, **kw: ak.<fn>(*a, **kw)。"
        )
