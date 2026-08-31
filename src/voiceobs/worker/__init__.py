"""Layer 3 — turn archived spans into turns and metrics.

Producer-agnostic by construction: it never names a span, attribute or event. Which
producer sent a call is `adapter_for()`'s problem, and there is always an answer.
"""

from voiceobs.worker.process import assemble, process

__all__ = ["assemble", "process"]
