from branches.music_local.agent import (
    DESCRIPTION,
    PRESETS,
    STATE_FILE,
    TRIGGERS,
    VERSION,
    MusicLocalAgent,
    adjust_volume,
    load_state,
    pause_player,
    play_query,
    replay_saved,
    resolve_stream_url,
    resume_player,
    save_state,
    stop_player,
)


_agent = MusicLocalAgent()


def can_handle(pregunta):
    return _agent.can_handle(pregunta)


def handle(pregunta):
    return _agent.handle(pregunta)


def status():
    return _agent.status()


def resolve_query(prompt_lower):
    return _agent.resolve_query(prompt_lower)
