from services.orchestrator.voice_control import (
    VoiceAction,
    VoiceState,
    apply_voice_action,
    should_barge_in,
)


def test_interrupt_speech_does_not_cancel_task_or_close_microphone():
    state = VoiceState(speaking=True, microphone_open=True, task_active=True)
    transition = apply_voice_action(state, VoiceAction.INTERRUPT_SPEECH)
    assert transition.state.speaking is False
    assert transition.state.microphone_open is True
    assert transition.state.task_active is True
    assert transition.state.task_cancelled is False


def test_stop_microphone_does_not_cancel_task_or_force_speech_stop():
    state = VoiceState(speaking=True, microphone_open=True, task_active=True)
    transition = apply_voice_action(state, VoiceAction.STOP_MICROPHONE)
    assert transition.state.microphone_open is False
    assert transition.state.speaking is True
    assert transition.state.task_active is True
    assert transition.state.task_cancelled is False


def test_cancel_task_is_distinct():
    state = VoiceState(speaking=True, microphone_open=True, task_active=True)
    transition = apply_voice_action(state, VoiceAction.CANCEL_TASK)
    assert transition.state.task_active is False
    assert transition.state.task_cancelled is True
    assert transition.state.speaking is True
    assert transition.state.microphone_open is True


def test_echo_does_not_trigger_false_barge_in():
    state = VoiceState(speaking=True, microphone_open=True, task_active=True)
    assert should_barge_in(state, detected_user_speech=True, echo_likelihood=0.95) is False
    assert should_barge_in(state, detected_user_speech=True, echo_likelihood=0.10) is True


def test_barge_in_requires_active_speech():
    state = VoiceState(speaking=False, microphone_open=True, task_active=True)
    assert should_barge_in(state, detected_user_speech=True, echo_likelihood=0.0) is False
