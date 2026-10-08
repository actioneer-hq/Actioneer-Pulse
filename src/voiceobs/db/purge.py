"""Delete calls (and a project's analysis) completely — every row that hangs off them."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.db.models import (
    AgentJourney,
    AgentScript,
    Annotation,
    AudioDiscrepancy,
    BackfillJob,
    Call,
    ChatMessage,
    Conversation,
    Event,
    IngestRun,
    Judgment,
    Label,
    Media,
    Metric,
    Moment,
    MomentCluster,
    RawFragment,
    ScriptProposal,
    TrainingSample,
    Transcript,
    Turn,
    Utterance,
)

_CALL_ROWS = (Annotation, AudioDiscrepancy, Event, IngestRun, Judgment, Label, Media, Metric, Moment,
              RawFragment, TrainingSample, Transcript, Turn, Utterance)


def purge_calls(db: Session, call_ids: list[str]) -> int:
    """Delete these calls (Call.id) and everything under them. Returns how many calls went."""
    if not call_ids:
        return 0
    # Lock the calls first: a judge worker attaching a judgment (or any row) to one of them mid-purge
    # would otherwise slip in between the deletes and break the final delete's foreign keys. With the
    # lock it waits, then finds the call gone and skips it.
    db.execute(select(Call.id).where(Call.id.in_(call_ids)).with_for_update())
    convs = select(Conversation.id).where(Conversation.call_id.in_(call_ids))
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(convs)))
    db.execute(delete(Conversation).where(Conversation.call_id.in_(call_ids)))
    for model in _CALL_ROWS:
        db.execute(delete(model).where(model.call_id.in_(call_ids)))
    db.execute(delete(Call).where(Call.id.in_(call_ids)))
    return len(call_ids)


def purge_agent_analysis(db: Session, agent_id: str) -> int:
    """A project's calls and analysis (clusters, script runs, uploads, journeys of scripts only it uses).
    The agent's own config rows are removed by the caller."""
    n = purge_calls(db, list(db.scalars(select(Call.id).where(Call.agent_id == agent_id))))
    for model in (MomentCluster, ScriptProposal, BackfillJob):
        db.execute(delete(model).where(model.agent_id == agent_id))
    mine = select(AgentScript.prompt_id).where(AgentScript.agent_id == agent_id)
    others = select(AgentScript.prompt_id).where(AgentScript.agent_id != agent_id)
    db.execute(delete(AgentJourney).where(AgentJourney.prompt_id.in_(mine), AgentJourney.prompt_id.not_in(others)))
    return n
