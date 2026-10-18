"""Unit tests for travel_agent/intent/complexity_classifier.py."""

from __future__ import annotations

import asyncio

import pytest

from travel_agent.intent.complexity_classifier import RequestComplexityClassifier
from travel_agent.intent.schemas import IntentContext


def _ctx(**kwargs) -> IntentContext:
    return IntentContext(current_message=kwargs.get("current_message", ""), **kwargs)


def _classify(message, context=None):
    return asyncio.run(RequestComplexityClassifier().classify(message, context or _ctx()))


@pytest.mark.parametrize(
    "message",
    [
        "确认",
        "可以",
        "按这个来",
        "取消",
        "删除第三天的浅草寺",
        "东京明天天气怎么样",
        "去日本需要签证吗",
        "第三天下午增加一个咖啡店",
        "我选第二个和第四个",
    ],
)
def test_simple_requests(message):
    result = _classify(message)
    assert result.level == "SIMPLE", f"{message!r} -> {result}"


@pytest.mark.parametrize(
    "message",
    [
        "这些传统景点太多了，多找一些瑜伽和疗愈活动，第三天下午重新排，其他不变。",
        "这些地方太游客了，我想体验当地年轻人平时会去的地方，但也不要全是酒吧。",
        "不是要删除浅草寺，只是把它从第三天移到第四天。",
        "第三个不要了，换成类似第二个但更小众的",
        "删除第三天下午的寺庙，多找两个涩谷附近的唱片店，然后把晚上的酒吧换成演出。",
        "这个不太适合我",
        "第三天下午再增加两个乌布附近的瑜伽课，其他安排不要动。",
    ],
)
def test_complex_requests(message):
    result = _classify(message)
    assert result.level == "COMPLEX", f"{message!r} -> {result}"


def test_short_reply_with_pending_confirmation_is_simple():
    ctx = _ctx(pending_confirmation={"question": "确认吗？"})
    result = _classify("嗯嗯", ctx)
    assert result.level == "SIMPLE"
