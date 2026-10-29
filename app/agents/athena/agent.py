"""Athena: chat with YouTube videos (RAG over transcripts). Start reading here.

Flows                  how it runs            started by
---------------------  ---------------------  ---------------------------------
athena.chat            inline (streams)       API
athena.ingest          queue: default         API (POST /videos), retry_failed
athena.transcribe      queue: media           ingest, when there are no captions
athena.retry_failed    queue: default         cron, 03:00 daily

Emits: athena.video_ready {"video_id"} when a video's chunks are stored.
"""

from app.agents.athena import service
from app.agents.athena.flows.chat.graph import graph as chat_graph
from app.agents.athena.flows.ingest.graph import graph as ingest_graph
from app.agents.athena.flows.retry_failed.graph import graph as retry_failed_graph
from app.agents.athena.flows.transcribe.graph import graph as transcribe_graph
from app.agents.athena.router import router
from app.agents.athena.schemas import (
    ChatInput,
    IngestInput,
    RetryFailedInput,
    TranscribeInput,
)
from app.runtime.spec import AgentSpec, ApiTrigger, CronTrigger, Flow

spec = AgentSpec(
    name="athena",
    router=router,
    flows=[
        Flow("chat", chat_graph, input=ChatInput, mode="inline"),
        Flow(
            "ingest",
            ingest_graph,
            input=IngestInput,
            queue="default",
            dedupe=lambda p: f"athena.ingest:{p.video_id}",
            on_failure=service.mark_failed,
        ),
        Flow(
            "transcribe",
            transcribe_graph,
            input=TranscribeInput,
            queue="media",
            max_attempts=2,
            timeout_s=3600,  # long videos take a while on CPU
            dedupe=lambda p: f"athena.transcribe:{p.video_id}",
            on_failure=service.mark_failed_and_delete_audio,
        ),
        Flow(
            "retry_failed",
            retry_failed_graph,
            input=RetryFailedInput,
            queue="default",
            max_attempts=1,
            dedupe=lambda p: "athena.retry_failed",
        ),
    ],
    triggers=[
        ApiTrigger(flow="chat"),
        ApiTrigger(flow="ingest"),
        CronTrigger("0 3 * * *", flow="retry_failed"),
    ],
    emits=["athena.video_ready"],
)
