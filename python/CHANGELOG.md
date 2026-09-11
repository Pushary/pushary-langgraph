# Changelog

## 0.4.0

**Native customer reviews for Python LangGraph.**

Preserve confirm, choice and text answers across checkpointed LangGraph interruptions. Verify callback payloads and keep customer, thread and native interrupt identities bound to the saved operation.

Only an explicit confirmation approves the protected action. Applications own persistent checkpoints and idempotent business effects.

Requires the shared Pushary SDK 2.1. Finish existing pending operations on their original SDK version before upgrading. The adapter is MIT-licensed; real phone delivery uses the hosted Partner service.

[Run or adapt the example](https://github.com/Pushary/pushary-langgraph/blob/main/python/README.md).
