from branches.music.agent import (
    DESCRIPTION,
    TRIGGERS,
    VERSION,
    MusicAgent,
    normalize_text,
)


_agent = MusicAgent()


def can_handle(pregunta):
    return _agent.can_handle(pregunta)


def handle(pregunta):
    return _agent.handle(pregunta)


def build_plan(pregunta):
    return _agent.build_plan(pregunta)


def execute_confirmed_plan(plan, pregunta):
    normalized = normalize_text(pregunta)
    response = _agent.execute_plan(plan, pregunta, normalized)
    try:
        _agent.memory.record_interaction(pregunta, normalized, plan, response)
    except Exception as exc:
        response.setdefault("debug", {})["memory_error"] = str(exc)
    return response


def status():
    return _agent.status()
