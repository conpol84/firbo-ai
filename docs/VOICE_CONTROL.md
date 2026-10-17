# Voice control semantics

FIRBO treats three user intents as different control actions:

- **Interrupt speech** — stop the assistant's current audio output while leaving the microphone and active task alone.
- **Stop microphone** — stop listening while leaving speech output and the active task alone.
- **Cancel task** — cancel the active task while leaving audio controls unchanged.

Barge-in is only accepted while FIRBO is speaking and the detected speech is not likely to be playback echo. The current reference threshold rejects interruptions at an echo likelihood of 0.65 or higher.

These semantics are intentionally independent so a user saying "stop talking" never destroys a running mission and "stop listening" never silently cancels work.
