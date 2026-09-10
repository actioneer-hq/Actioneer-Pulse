"""Anonymous, opt-out usage telemetry. Aggregate product signals only — never tenant data.

Import from the worker/api layer only (it touches config/db); keep it out of core/frameworks."""

from voiceobs.telemetry.client import flush
from voiceobs.telemetry.events import error_occurred, feature_used, heartbeat

__all__ = ["error_occurred", "feature_used", "flush", "heartbeat"]
