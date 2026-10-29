import pytest
from pydantic import BaseModel

from app.runtime.http import _ndjson
from app.runtime.registry import Registry, registry
from app.runtime.spec import AgentSpec, ApiTrigger, CronTrigger, EventTrigger, Flow


class Empty(BaseModel):
    pass


def _flow(name: str, **kw) -> Flow:
    return Flow(name, graph=None, input=Empty, **kw)


def test_register_indexes_flows_and_triggers():
    reg = Registry()
    reg.register(
        AgentSpec(
            name="a",
            flows=[_flow("chat", mode="inline"), _flow("work")],
            triggers=[ApiTrigger("chat"), CronTrigger("* * * * *", "work")],
            emits=["a.done"],
        )
    )
    reg.register(AgentSpec(name="b", flows=[_flow("react")], triggers=[EventTrigger("a.done", "react")]))
    reg.validate()

    assert set(reg.flows) == {"a.chat", "a.work", "b.react"}
    assert reg.api_flows == {"a.chat"}
    assert [c.flow_id for c in reg.crons] == ["a.work"]
    assert [lst.flow_id for lst in reg.listeners["a.done"]] == ["b.react"]


def test_trigger_must_point_to_existing_flow():
    with pytest.raises(ValueError, match="unknown flow"):
        Registry().register(AgentSpec(name="a", flows=[], triggers=[ApiTrigger("nope")]))


def test_inline_flow_cannot_be_cron_or_event_triggered():
    with pytest.raises(ValueError, match="inline"):
        Registry().register(
            AgentSpec(name="a", flows=[_flow("chat", mode="inline")], triggers=[CronTrigger("* * * * *", "chat")])
        )


def test_events_must_be_namespaced_by_agent():
    with pytest.raises(ValueError, match="must start with"):
        Registry().register(AgentSpec(name="a", flows=[], emits=["b.done"]))


def test_listening_to_unknown_event_fails_validation():
    reg = Registry()
    reg.register(AgentSpec(name="b", flows=[_flow("react")], triggers=[EventTrigger("a.typo", "react")]))
    with pytest.raises(ValueError, match="no agent emits"):
        reg.validate()


def test_discover_finds_athena():
    registry.discover()
    assert {"athena.chat", "athena.ingest", "athena.transcribe", "athena.retry_failed"} <= set(registry.flows)
    assert registry.flows["athena.transcribe"].queue == "media"


def test_ndjson_appends_done_or_error():
    def failing():
        yield {"type": "token", "text": "b"}
        raise RuntimeError("boom")

    ok = list(_ndjson({"type": "token", "text": "a"}, iter([])))
    assert ok == ['{"type": "token", "text": "a"}\n', '{"type": "done"}\n']

    bad = list(_ndjson(None, failing()))
    assert bad[-1] == '{"type": "error", "message": "RuntimeError: boom"}\n'
