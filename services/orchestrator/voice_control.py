from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class VoiceAction(str, Enum):
    INTERRUPT_SPEECH = "interrupt_speech"
    STOP_MICROPHONE = "stop_microphone"
    CANCEL_TASK = "cancel_task"


@dataclass(frozen=True)
class VoiceState:
    speaking: bool = False
    microphone_open: bool = True
    task_active: bool = False
    task_cancelled: bool = False


@dataclass(frozen=True)
class VoiceTransition:
    state: VoiceState
    action: VoiceAction
    changed: bool
    event: str


def apply_voice_action(state: VoiceState, action: VoiceAction) -> VoiceTransition:
    if action is VoiceAction.INTERRUPT_SPEECH:
        changed = state.speaking
        return VoiceTransition(
            state=replace(state, speaking=False),
            action=action,
            changed=changed,
            event="speech_interrupted" if changed else "speech_already_silent",
        )

    if action is VoiceAction.STOP_MICROPHONE:
        changed = state.microphone_open
        return VoiceTransition(
            state=replace(state, microphone_open=False),
            action=action,
            changed=changed,
            event="microphone_stopped" if changed else "microphone_already_stopped",
        )

    if action is VoiceAction.CANCEL_TASK:
        changed = state.task_active and not state.task_cancelled
        return VoiceTransition(
            state=replace(state, task_active=False, task_cancelled=state.task_cancelled or changed),
            action=action,
            changed=changed,
            event="task_cancelled" if changed else "no_active_task",
        )

    raise ValueError(f"unsupported_voice_action:{action}")


def should_barge_in(state: VoiceState, detected_user_speech: bool, echo_likelihood: float) -> bool:
    if not state.speaking or not detected_user_speech:
        return False
    return echo_likelihood < 0.65
