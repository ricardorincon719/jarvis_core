from branches.music.agent import (
    DESCRIPTION,
    TRIGGERS,
    VERSION,
    MusicAgent,
)


_agent = MusicAgent()


def can_handle(pregunta):
    return _agent.can_handle(pregunta)


def handle(pregunta):
    return _agent.handle(pregunta)
