"""A minimal cascade (STT->LLM->TTS) LiveKit agent for end-to-end testing Pulse.

It does two things: talk to you in the browser (LiveKit Agents Playground), and export
its OpenTelemetry traces to Pulse's ingest endpoint. Pulse's LiveKit adapter turns those spans
into a Trace, the worker computes metrics, and you can then read them back.

Run: see tests/e2e/README.md. Not part of the pytest suite — it needs live creds and a mic.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.agents.telemetry import set_tracer_provider
from livekit.plugins import openai, silero
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

load_dotenv()


def _setup_tracing() -> None:
    """Point LiveKit's tracer at Pulse. VO_OTLP_ENDPOINT is Pulse's /v1/traces URL."""
    endpoint = os.environ["VO_OTLP_ENDPOINT"]  # e.g. http://localhost:8000/v1/traces
    exporter = OTLPSpanExporter(endpoint=endpoint)  # protobuf/HTTP; Pulse decodes it
    provider = TracerProvider(resource=Resource.create({"service.name": "livekit"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    set_tracer_provider(provider)  # LiveKit's, not opentelemetry.trace's


async def entrypoint(ctx: JobContext) -> None:
    _setup_tracing()
    await ctx.connect()

    session = AgentSession(
        stt=openai.STT(),                       # cascade: separate STT/LLM/TTS spans
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(voice="alloy"),
        vad=silero.VAD.load(),
    )
    await session.start(
        agent=Agent(
            instructions=(
                "You are a friendly outbound assistant confirming an appointment. "
                "Greet the caller, ask if the time still works, and thank them. Keep "
                "replies short."
            ),
        ),
        room=ctx.room,
    )
    await session.generate_reply(instructions="Greet the caller and open the conversation.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
