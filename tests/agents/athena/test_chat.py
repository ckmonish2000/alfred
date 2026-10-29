from app.agents.athena.flows.chat.nodes import (
    Source,
    build_messages,
    format_ts,
    retrieval_query,
)
from app.agents.athena.models import Video
from app.agents.athena.schemas import ChatMessage


def test_format_ts():
    assert format_ts(5.9) == "0:05"
    assert format_ts(195) == "3:15"
    assert format_ts(3723) == "1:02:03"


def test_retrieval_query_includes_previous_question():
    history = [
        ChatMessage(role="user", content="What models were released?"),
        ChatMessage(role="assistant", content="Two models."),
    ]
    assert retrieval_query(history, "Which is faster?") == "What models were released?\nWhich is faster?"
    assert retrieval_query([], "Hello") == "Hello"


def test_build_messages():
    video = Video(youtube_id="abc", title="Zoo", channel="jawed")
    sources = [Source(chunk_index=0, start_sec=1.2, end_sec=18.9, text="elephants", score=0.9)]
    history = [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="hello")]

    messages = build_messages(video, sources, history, "What animals?")

    assert messages[0]["role"] == "system"
    assert "Zoo" in messages[0]["content"]
    assert "[0:01 - 0:18]\nelephants" in messages[0]["content"]
    assert messages[1:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "What animals?"},
    ]
