"""Task 7: ⑨ explainer。"""
import json
from panwen.agent import explainer as ex
from panwen.agent.types import ChatResult


class _BE:
    def __init__(self, payload): self._p = payload
    def chat(self, messages, **kw):
        return ChatResult(content=json.dumps(self._p), tool_calls=[], raw={})


def test_explain_parses_json():
    e = ex.explain("茅台ROE", "SELECT roe...", [{"roe": 30.0}], False,
                   _BE({"assumptions": ["a"], "confidence": 0.9, "summary": "ROE 30%"}))
    assert e.confidence == 0.9 and e.summary == "ROE 30%"


def test_low_confidence_caps_at_half():
    e = ex.explain("x", "SELECT 1", None, True,
                   _BE({"assumptions": [], "confidence": 0.9, "summary": "s"}))
    assert e.confidence <= 0.5
