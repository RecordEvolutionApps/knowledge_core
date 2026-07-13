"""Register the knowledge RPCs on an injected ironflock SDK handle.

Requires ironflock >= 1.5.3 (`register_device_function`). The registered
URI is `{swarm_key}.{device_key}.{app_key}.{env}.{topic}` and the SDK
replays registrations on reconnect, so one call here is durable.
"""

DEFAULT_TOPICS = ("app_knowledge.list", "app_knowledge.get")

from .handlers import rpc_handlers


async def register_knowledge_tools(ironflock, library, topics=DEFAULT_TOPICS, report=None):
    """Register the list/get endpoints. Returns the list of topics that
    FAILED to register (empty = success). Never raises: a knowledge outage
    must degrade the assistant, not the app.

    `report` is an optional async callable ``report(msg, user_message=...)``
    (e.g. collector_core's ``collector.report_error``) invoked once when any
    registration fails.

    NOTE: ``register_device_function`` swallows exceptions internally and
    returns ``None`` on failure — checking the return value is the only way
    to detect it.
    """
    handlers = rpc_handlers(library)
    list_topic, get_topic = topics
    failed = []
    for topic, handler in ((list_topic, handlers["list"]), (get_topic, handlers["get"])):
        try:
            reg = await ironflock.register_device_function(topic, handler)
        except Exception:
            reg = None
        if reg is None:
            failed.append(topic)
    if failed and report is not None:
        try:
            await report(
                f"failed to register knowledge RPC(s): {', '.join(failed)}",
                user_message=(
                    "The AI assistant's knowledge tools could not be registered "
                    "on this device - it will answer from general knowledge only."
                ),
            )
        except Exception:
            pass
    return failed
