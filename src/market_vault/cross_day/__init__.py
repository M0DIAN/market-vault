"""Parallel TS2 Cross-Day / TRADING_DAYS Label L2 logical authority only."""

from ._validation import CrossDayLabelError
from .assembly import CrossDayLabelAssemblyResult, assemble_cross_day_labels
from .execution import CrossDayLabelExecutionResult, execute_cross_day_labels, validate_cross_day_execution_result
from .models import CrossDayLabelDecision, CrossDayLabelSampleBinding, CrossDayLabelValueResult
from .schedule import TradingDayRecord, TradingDaySchedulePin, VerifiedTradingDaySchedule, verify_trading_day_schedule

__all__ = [
    "CrossDayLabelError", "TradingDayRecord", "TradingDaySchedulePin", "VerifiedTradingDaySchedule",
    "verify_trading_day_schedule", "CrossDayLabelDecision", "CrossDayLabelSampleBinding",
    "CrossDayLabelValueResult", "CrossDayLabelAssemblyResult", "assemble_cross_day_labels",
    "CrossDayLabelExecutionResult", "execute_cross_day_labels", "validate_cross_day_execution_result",
]
