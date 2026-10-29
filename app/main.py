from fastapi import FastAPI

from app.core.logging import setup_logging
from app.runtime import http as runtime_http
from app.runtime.registry import registry

setup_logging()
registry.discover()

app = FastAPI(title="Alfred")
app.include_router(runtime_http.router)
for agent in registry.agents.values():
    if agent.router is not None:
        app.include_router(agent.router, prefix=f"/agents/{agent.name}")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agents")
def list_agents():
    return [
        {
            "name": agent.name,
            "flows": [
                {"name": f.name, "mode": f.mode, "queue": f.queue if f.mode == "queued" else None}
                for f in agent.flows
            ],
            "api_flows": sorted(f for f in registry.api_flows if f.startswith(f"{agent.name}.")),
            "emits": agent.emits,
        }
        for agent in registry.agents.values()
    ]
