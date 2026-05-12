from branches.domotica.agent import (
    DEVICE_NAME,
    SCENES,
    TRIGGERS,
    DomoticaAgent,
    has_any,
    is_light_target,
    is_turn_off_intent,
    is_turn_on_intent,
    normalize_text,
)


VERSION = "2.0.0"
DESCRIPTION = "Agente domotico local con memoria persistente y planes validados para PEARL HOME"

_agent = DomoticaAgent()

# Compatibilidad con nombres historicos usados por pruebas/manuales.
SCENE_LECTURA = SCENES["lectura"]
SCENE_RELAX = SCENES["relax"]
SCENE_NOCHE = SCENES["noche"]
SCENE_NORMAL = SCENES["normal"]
SCENE_FRIA = SCENES["fria"]
SCENE_CALIDA = SCENES["calida"]
SCENE_ROJO = SCENES["rojo"]
SCENE_VERDE = SCENES["verde"]
SCENE_AZUL = SCENES["azul"]


def can_handle(pregunta):
    return _agent.can_handle(pregunta)


def handle(pregunta):
    return _agent.handle(pregunta)


def get_current_scene_snapshot():
    return _agent._get_current_scene_snapshot(DEVICE_NAME)


def save_last_before_off():
    scene = get_current_scene_snapshot()
    return _agent.memory.save_last_before_off(scene)


def load_last_before_off():
    return _agent.memory.load_last_before_off()


def apply_scene(scene: dict):
    return _agent.service.apply_scene(DEVICE_NAME, scene)
