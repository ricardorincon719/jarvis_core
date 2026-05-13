import re
import unicodedata
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from branches.domotica.memory import DomoticaMemory


DEVICE_NAME = "lamp_quarto"

SCENES = {
    "lectura": {"switch": True, "mode": "white", "brightness": 1000, "temp": 850},
    "relax": {"switch": True, "mode": "white", "brightness": 350, "temp": 150},
    "noche": {"switch": True, "mode": "white", "brightness": 80, "temp": 60},
    "normal": {"switch": True, "mode": "white", "brightness": 800, "temp": 650},
    "fria": {"switch": True, "mode": "white", "brightness": 700, "temp": 1000},
    "calida": {"switch": True, "mode": "white", "brightness": 1000, "temp": 0},
    "rojo": {"switch": True, "mode": "colour", "rgb": [255, 0, 0], "color": "red"},
    "verde": {"switch": True, "mode": "colour", "rgb": [0, 255, 0], "color": "green"},
    "azul": {"switch": True, "mode": "colour", "rgb": [0, 0, 255], "color": "blue"},
}

SCENE_ALIASES = {
    "lectura": ["lectura", "leer"],
    "relax": ["relax", "relajado", "relajante", "descanso"],
    "noche": ["noche", "dormir", "sueno", "sueño"],
    "normal": ["normal", "default"],
    "fria": ["fria", "frio", "fría", "frío", "blanca"],
    "calida": ["calida", "calido", "cálida", "cálido", "warm"],
    "rojo": ["rojo", "roja", "red"],
    "verde": ["verde", "green"],
    "azul": ["azul", "blue"],
}

TRIGGERS = [
    "luz", "luces", "lampara", "lámpara", "bombilla", "foco", "cuarto", "sala",
    "domotica", "domótica", "ambiente", "escena", "automatizacion", "automatización",
    "dispositivo", "dispositivos", "descubrir", "descubre", "buscar", "agregar",
    "lectura", "relax", "noche", "normal", "calida", "cálida", "fria", "fría",
    "rojo", "roja", "verde", "azul", "brillo", "temperatura", "estado",
    "apagar", "apaga", "encender", "enciende", "prender", "prende",
    "restaurar", "deshacer", "como estaba", "último estado", "ultimo estado",
    "aprende", "recuerda", "patron", "patrón", "memoria",
]

ALLOWED_ACTIONS = {
    "apply_scene",
    "turn_on",
    "turn_off",
    "status",
    "restore_before_off",
    "restore_previous_state",
    "memory_summary",
    "remember_note",
    "list_scenes",
    "suggest_scene",
    "approve_scene",
    "reject_scene",
    "list_devices",
    "discover_devices",
    "list_device_candidates",
}


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^\w\s%]", " ", text)
    return " ".join(text.split())


def normalize_compact(text: str) -> str:
    return normalize_text(text).replace(" ", "_")


def has_any(text: str, words: List[str]) -> bool:
    return any(normalize_text(word) in text for word in words)


def is_light_target(text: str) -> bool:
    return has_any(text, ["luz", "luces", "lampara", "cuarto", "sala", "foco", "bombilla"])


def is_turn_on_intent(text: str) -> bool:
    return has_any(text, ["encender", "enciende", "prender", "prende", "activar"])


def is_turn_off_intent(text: str) -> bool:
    return has_any(text, ["apagar", "apaga"])


def percent_to_brightness(percent: int) -> int:
    percent = max(0, min(100, int(percent)))
    if percent == 0:
        return 10
    return int(10 + ((1000 - 10) * (percent / 100.0)))


def percent_to_temp(percent: int) -> int:
    percent = max(0, min(100, int(percent)))
    return int(1000 * (percent / 100.0))


def scene_copy(name: str) -> Dict:
    return deepcopy(SCENES[name])


class DomoticaAgent:
    def __init__(self, service=None, memory: Optional[DomoticaMemory] = None):
        self._service = service
        self.memory = memory or DomoticaMemory()

    @property
    def service(self):
        if self._service is None:
            from branches.domotica.service import DomoticaService

            self._service = DomoticaService()
        return self._service

    def can_handle(self, prompt: str) -> bool:
        text = normalize_text(prompt)
        return any(normalize_text(trigger) in text for trigger in TRIGGERS)

    def handle(self, prompt: str) -> Dict:
        normalized = normalize_text(prompt)
        try:
            plan = self.build_plan(prompt)
            response = self.execute_plan(plan, prompt, normalized)
        except Exception as exc:
            plan = {"intent": "error", "actions": [], "error": str(exc)}
            response = {
                "respuesta": f"Error en agente domotico: {exc}",
                "cerebro": "DomoticaAgent",
                "debug": {"plan": plan},
            }

        try:
            self.memory.record_interaction(prompt, normalized, plan, response)
        except Exception as exc:
            response.setdefault("debug", {})["memory_error"] = str(exc)

        return response

    def build_plan(self, prompt: str) -> Dict:
        text = normalize_text(prompt)
        device_name = self._resolve_device_name(text)

        if self._is_memory_query(text):
            return self._plan("memory_summary", [{"type": "memory_summary"}])

        if self._is_scene_list_query(text):
            return self._plan("list_scenes", [{"type": "list_scenes"}])

        if self._is_device_list_query(text):
            return self._plan("list_devices", [{"type": "list_devices"}])

        if self._is_device_candidate_query(text):
            return self._plan("list_device_candidates", [{"type": "list_device_candidates"}])

        if self._is_discovery_query(text):
            return self._plan("discover_devices", [{"type": "discover_devices"}])

        if has_any(text, ["sugerencia", "sugerir", "que recomiendas", "que sugieres"]):
            return self._plan("suggest_scene", [{"type": "suggest_scene", "intent": "domotica"}])

        note = self._extract_note(text)
        if note:
            return self._plan("remember_note", [{"type": "remember_note", "note": note, "category": "user_preference"}])

        approval = self._extract_scene_status_change(text)
        if approval:
            action_type, query = approval
            return self._plan(action_type, [{"type": action_type, "query": query}])

        learned_scene = self._extract_learned_scene_activation(text)
        if learned_scene:
            return self._plan("activate_learned_scene", [{"type": "apply_learned_scene", "query": learned_scene}])

        if has_any(text, ["deshacer", "como estaba"]):
            return self._plan("restore_previous_state", [{"type": "restore_previous_state", "device": device_name}])

        if has_any(text, ["restaurar", "ultimo estado", "último estado"]):
            return self._plan("restore_before_off", [{"type": "restore_before_off", "device": device_name}])

        if "estado" in text and (is_light_target(text) or "domotica" in text):
            return self._plan("status", [{"type": "status", "device": device_name}])

        scene_name, scene = self._parse_scene(text)
        brightness_percent = self._parse_percent(text, ["brillo", "intensidad"])
        temp_percent = self._parse_percent(text, ["temperatura"])

        if scene:
            if brightness_percent is not None and scene.get("mode") == "white":
                scene["brightness"] = percent_to_brightness(brightness_percent)
            if temp_percent is not None and scene.get("mode") == "white":
                scene["temp"] = percent_to_temp(temp_percent)
            return self._plan(
                f"apply_{scene_name}",
                [{"type": "apply_scene", "device": device_name, "scene_name": scene_name, "scene": scene}],
            )

        if brightness_percent is not None and is_light_target(text):
            scene = {
                "switch": True,
                "mode": "white",
                "brightness": percent_to_brightness(brightness_percent),
                "temp": 650,
            }
            return self._plan(
                "set_brightness",
                [{"type": "apply_scene", "device": device_name, "scene_name": f"brillo_{brightness_percent}", "scene": scene}],
            )

        if temp_percent is not None and is_light_target(text):
            scene = {
                "switch": True,
                "mode": "white",
                "brightness": 800,
                "temp": percent_to_temp(temp_percent),
            }
            return self._plan(
                "set_temperature",
                [{"type": "apply_scene", "device": device_name, "scene_name": f"temperatura_{temp_percent}", "scene": scene}],
            )

        if is_turn_off_intent(text) and is_light_target(text):
            return self._plan("turn_off", [{"type": "turn_off", "device": device_name}])

        if is_turn_on_intent(text) and is_light_target(text):
            return self._plan("turn_on", [{"type": "turn_on", "device": device_name}])

        return self._plan("unknown", [])

    def execute_plan(self, plan: Dict, prompt: str, normalized: str) -> Dict:
        actions = plan.get("actions") or []
        if not actions:
            return {
                "respuesta": f"No reconoci un comando domotico accionable: '{prompt}'",
                "cerebro": "DomoticaAgent",
                "debug": {"normalized": normalized, "plan": plan},
            }

        self._validate_plan(plan)
        results = []
        memory_updates = []

        for action in actions:
            action_type = action.get("type")

            if action_type == "memory_summary":
                summary = self.memory.summary()
                return self._memory_response(summary, plan)

            if action_type == "remember_note":
                note = self.memory.remember_note(action.get("note") or "", action.get("category") or "general")
                return {
                    "respuesta": "Lo guarde en la memoria domotica.",
                    "cerebro": "DomoticaAgent",
                    "debug": {"plan": plan, "note": note},
                }

            if action_type == "list_scenes":
                scenes = self.memory.list_scenes()
                return self._scenes_response(scenes, plan)

            if action_type == "list_devices":
                devices = self.service.devices()
                return self._devices_response(devices, plan)

            if action_type == "list_device_candidates":
                candidates = self.service.pending_devices()
                return self._device_candidates_response(candidates, plan)

            if action_type == "discover_devices":
                try:
                    discovery = self.service.discover_devices()
                except Exception as exc:
                    return {
                        "respuesta": f"No pude escanear dispositivos Tuya: {exc}",
                        "cerebro": "DomoticaAgent",
                        "debug": {"plan": plan, "error": str(exc)},
                    }
                return self._discovery_response(discovery, plan)

            if action_type == "suggest_scene":
                suggestion = self.memory.suggest_scene(action.get("intent"))
                if not suggestion:
                    return {
                        "respuesta": "Todavia no tengo un patron domotico suficiente para sugerir una escena.",
                        "cerebro": "DomoticaAgent",
                        "debug": {"plan": plan},
                    }
                return {
                    "respuesta": suggestion["suggestion"],
                    "cerebro": "DomoticaAgent",
                    "requires_confirmation": True,
                    "debug": {"plan": plan, "suggestion": suggestion},
                }

            if action_type in {"approve_scene", "reject_scene"}:
                status = "approved" if action_type == "approve_scene" else "rejected"
                scene = self.memory.find_scene(action.get("query") or "")
                if not scene:
                    return {
                        "respuesta": "No encontre esa escena aprendida.",
                        "cerebro": "DomoticaAgent",
                        "debug": {"plan": plan},
                    }
                updated = self.memory.update_scene_status(scene["id"], status)
                label = "aprobada" if status == "approved" else "rechazada"
                return {
                    "respuesta": f"Escena {label}: {updated.get('name')}",
                    "cerebro": "DomoticaAgent",
                    "debug": {"plan": plan, "scene": updated},
                }

            if action_type == "apply_learned_scene":
                scene = self.memory.find_scene(action.get("query") or "")
                if not scene:
                    return {
                        "respuesta": "No encontre esa escena aprendida.",
                        "cerebro": "DomoticaAgent",
                        "debug": {"plan": plan},
                    }
                if scene.get("status") != "approved":
                    return {
                        "respuesta": f"La escena '{scene.get('name')}' existe, pero necesita aprobacion antes de ejecutarse.",
                        "cerebro": "DomoticaAgent",
                        "requires_confirmation": True,
                        "debug": {"plan": plan, "scene": scene},
                    }
                learned_actions = scene.get("actions") or []
                for learned_action in learned_actions:
                    learned_action = dict(learned_action)
                    learned_action["learned_scene_id"] = scene.get("id")
                    results.append(self._execute_physical_action(learned_action, prompt))
                self.memory.mark_scene_executed(scene.get("id"))
                continue

            result = self._execute_physical_action(action, prompt)
            results.append(result)

            if action_type == "apply_scene" and result.get("ok"):
                memory_updates.append(
                    self.memory.record_light_event(
                        action.get("device") or DEVICE_NAME,
                        plan.get("intent") or "domotica",
                        action.get("scene_name") or "custom",
                        action.get("scene") or {},
                        result,
                        prompt,
                    )
                )

        return self._action_response(plan, results, memory_updates)

    def _execute_physical_action(self, action: Dict, prompt: str) -> Dict:
        action_type = action.get("type")
        device = action.get("device") or DEVICE_NAME

        if action_type == "status":
            return self.service.status(device)

        if action_type == "turn_on":
            return self.service.turn_on(device)

        if action_type == "turn_off":
            snapshot_warning = None
            try:
                self.memory.save_last_before_off(self._get_current_scene_snapshot(device))
            except Exception as exc:
                snapshot_warning = str(exc)
            result = self.service.turn_off(device)
            if snapshot_warning:
                result["snapshot_warning"] = snapshot_warning
            return result

        if action_type == "restore_before_off":
            scene = self.memory.load_last_before_off()
            result = self.service.apply_scene(device, scene)
            result["scene"] = scene
            return result

        if action_type == "restore_previous_state":
            return self.service.restore_previous_state(device)

        if action_type in {"apply_scene", "apply_learned_scene"}:
            return self.service.apply_scene(device, action.get("scene") or {})

        raise ValueError(f"Accion no soportada: {action_type}")

    def _get_current_scene_snapshot(self, device: str) -> Dict:
        status = self.service.status(device)
        inner_status = status.get("status") or {}
        dps_raw = inner_status.get("dps") or {}
        dps = {str(key): value for key, value in dps_raw.items()}
        scene = {
            "switch": bool(dps.get("20", False)),
            "mode": dps.get("21", "white"),
        }
        if scene["mode"] == "white":
            scene["brightness"] = int(dps.get("22", 500))
            scene["temp"] = int(dps.get("23", 500))
        elif scene["mode"] == "colour":
            scene["raw_colour"] = dps.get("24")
            scene["color"] = dps.get("24")
        return scene

    def _resolve_device_name(self, text: str) -> str:
        try:
            devices = self.service.devices()
        except Exception:
            return DEVICE_NAME

        for name, cfg in devices.items():
            aliases = {
                normalize_text(name),
                normalize_compact(name),
                normalize_text(str(cfg.get("label") or "")),
                normalize_compact(str(cfg.get("label") or "")),
                normalize_text(str(cfg.get("room") or "")),
            }
            aliases.update(part for alias in list(aliases) for part in alias.split("_") if len(part) >= 3)
            aliases.difference_update({"lamp", "light", "tuya", "luz", "luces", "lampara", "foco"})
            aliases.discard("")
            if any(alias and alias in text for alias in aliases):
                return name

        return DEVICE_NAME

    def _devices_response(self, devices: Dict, plan: Dict) -> Dict:
        total = len(devices)
        names = ", ".join(
            cfg.get("label") or name
            for name, cfg in devices.items()
        ) or "ninguno"
        return {
            "respuesta": f"Dispositivos domoticos registrados: {total}. {names}.",
            "cerebro": "DomoticaAgent",
            "debug": {"plan": plan, "devices": devices},
        }

    def _device_candidates_response(self, candidates: List[Dict], plan: Dict) -> Dict:
        if not candidates:
            return {
                "respuesta": "No hay dispositivos domoticos pendientes de aprobacion.",
                "cerebro": "DomoticaAgent",
                "debug": {"plan": plan, "candidates": []},
            }
        return {
            "respuesta": f"Hay {len(candidates)} dispositivo(s) pendiente(s) de aprobacion.",
            "cerebro": "DomoticaAgent",
            "requires_confirmation": True,
            "debug": {"plan": plan, "candidates": candidates},
        }

    def _discovery_response(self, discovery: Dict, plan: Dict) -> Dict:
        summary = discovery.get("summary") or {}
        new_count = int(summary.get("new") or 0)
        known_count = int(summary.get("known") or 0)
        if new_count:
            text = f"Detecte {new_count} dispositivo(s) nuevo(s) Tuya y los deje pendientes de aprobacion."
        elif known_count:
            text = f"Detecte {known_count} dispositivo(s) Tuya ya registrado(s)."
        else:
            text = "No detecte dispositivos Tuya nuevos en la red local."
        return {
            "respuesta": text,
            "cerebro": "DomoticaAgent",
            "requires_confirmation": bool(new_count),
            "debug": {"plan": plan, "discovery": discovery},
        }

    def _validate_plan(self, plan: Dict):
        for action in plan.get("actions") or []:
            action_type = action.get("type")
            if action_type == "apply_learned_scene":
                continue
            if action_type not in ALLOWED_ACTIONS:
                raise ValueError(f"Accion no permitida: {action_type}")
            if action_type == "apply_scene":
                self._validate_scene(action.get("scene") or {})

    def _validate_scene(self, scene: Dict):
        if not isinstance(scene, dict):
            raise ValueError("La escena debe ser un objeto")
        if "switch" in scene and not isinstance(scene["switch"], bool):
            raise ValueError("switch debe ser booleano")
        mode = scene.get("mode")
        if mode and mode not in {"white", "colour"}:
            raise ValueError(f"Modo de luz no permitido: {mode}")
        for key in ("brightness", "temp"):
            if key in scene:
                value = int(scene[key])
                if value < 0 or value > 1000:
                    raise ValueError(f"{key} fuera de rango: {value}")
        if "rgb" in scene:
            rgb = scene["rgb"]
            if not isinstance(rgb, list) or len(rgb) != 3:
                raise ValueError("rgb debe tener tres valores")
            for value in rgb:
                number = int(value)
                if number < 0 or number > 255:
                    raise ValueError(f"rgb fuera de rango: {number}")

    def _plan(self, intent: str, actions: List[Dict]) -> Dict:
        return {
            "agent": "domotica",
            "intent": intent,
            "requires_confirmation": False,
            "actions": actions,
        }

    def _parse_scene(self, text: str) -> Tuple[Optional[str], Optional[Dict]]:
        for scene_name, aliases in SCENE_ALIASES.items():
            if has_any(text, aliases):
                return scene_name, scene_copy(scene_name)
        return None, None

    def _parse_percent(self, text: str, hints: List[str]) -> Optional[int]:
        if not has_any(text, hints):
            return None
        match = re.search(r"\b(\d{1,3})\s*%", text)
        if not match:
            match = re.search(r"\bal\s+(\d{1,3})\b", text)
        if not match:
            return None
        value = int(match.group(1))
        if value < 0 or value > 100:
            raise ValueError(f"Porcentaje fuera de rango: {value}")
        return value

    def _is_memory_query(self, text: str) -> bool:
        return (
            "memoria" in text
            or has_any(text, ["que aprendiste", "que recuerdas", "historial domotico"])
        ) and has_any(text, ["domotica", "luz", "luces", "lampara", "recuerdas", "aprendiste"])

    def _is_scene_list_query(self, text: str) -> bool:
        return has_any(text, ["patrones", "escenas aprendidas", "escenas guardadas", "automatizaciones"])

    def _is_device_list_query(self, text: str) -> bool:
        return has_any(text, ["dispositivos", "lamparas registradas", "lámparas registradas"]) and has_any(text, ["lista", "muestra", "ver", "registradas"])

    def _is_device_candidate_query(self, text: str) -> bool:
        return has_any(text, ["pendientes", "candidatos"]) and has_any(text, ["dispositivos", "lamparas", "lámparas", "domotica"])

    def _is_discovery_query(self, text: str) -> bool:
        return has_any(text, ["descubrir", "descubre", "buscar", "busca", "escanear", "escanea", "detectar", "detecta"]) and has_any(text, ["dispositivo", "dispositivos", "lampara", "lamparas", "lámpara", "lámparas", "tuya"])

    def _extract_note(self, text: str) -> Optional[str]:
        for marker in ("recuerda que", "aprende que", "memoriza que"):
            marker = normalize_text(marker)
            if marker in text:
                note = text.split(marker, 1)[1].strip()
                return note if note else None
        return None

    def _extract_scene_status_change(self, text: str) -> Optional[Tuple[str, str]]:
        for word in ("aprobar", "aprueba"):
            if word in text:
                return "approve_scene", self._strip_scene_command(text, word)
        for word in ("rechazar", "rechaza"):
            if word in text:
                return "reject_scene", self._strip_scene_command(text, word)
        return None

    def _extract_learned_scene_activation(self, text: str) -> Optional[str]:
        if "activar escena" in text:
            return text.split("activar escena", 1)[1].strip()
        if "activa escena" in text:
            return text.split("activa escena", 1)[1].strip()
        return None

    def _strip_scene_command(self, text: str, word: str) -> str:
        value = text.split(word, 1)[1].strip()
        value = value.replace("escena", "", 1).strip()
        return value

    def _memory_response(self, summary: Dict, plan: Dict) -> Dict:
        return {
            "respuesta": (
                "Memoria domotica: "
                f"{summary['interactions']} interacciones, "
                f"{summary['light_events']} eventos de luz, "
                f"{summary['candidate_scenes']} escenas candidatas y "
                f"{summary['approved_scenes']} aprobadas."
            ),
            "cerebro": "DomoticaAgent",
            "debug": {"plan": plan, "memory": summary},
        }

    def _scenes_response(self, scenes: List[Dict], plan: Dict) -> Dict:
        if not scenes:
            text = "Todavia no hay escenas aprendidas."
        else:
            labels = [
                f"{scene.get('id')} ({scene.get('status')}): {scene.get('name')}"
                for scene in scenes[-5:]
            ]
            text = "Escenas aprendidas: " + " | ".join(labels)
        return {
            "respuesta": text,
            "cerebro": "DomoticaAgent",
            "debug": {"plan": plan, "scenes": scenes},
        }

    def _action_response(self, plan: Dict, results: List[Dict], memory_updates: List[Dict]) -> Dict:
        first = results[0] if results else {}
        ok = all(bool(result.get("ok")) for result in results if isinstance(result, dict))
        ip = first.get("ip") if isinstance(first, dict) else None
        intent = plan.get("intent") or "domotica"

        if intent.startswith("apply_"):
            answer = f"Escena {intent.replace('apply_', '')} aplicada"
        elif intent == "turn_on":
            answer = "Luz encendida"
        elif intent == "turn_off":
            answer = "Luz apagada"
        elif intent == "status":
            answer = "Luz disponible"
        elif intent == "restore_before_off":
            answer = "Ultimo estado antes de apagar restaurado"
        elif intent == "restore_previous_state":
            answer = "Estado anterior restaurado"
        elif intent == "activate_learned_scene":
            answer = "Escena aprendida activada"
        else:
            answer = "Accion domotica ejecutada"

        if ip:
            answer = f"{answer} ({ip})"
        if not ok and results:
            answer = f"{answer}, pero la confirmacion no fue completa"

        created = []
        for update in memory_updates:
            created.extend(update.get("candidates_created") or [])
        if created:
            answer += ". Detecte un nuevo patron y lo deje como candidato."

        return {
            "respuesta": answer,
            "cerebro": "DomoticaAgent",
            "ok": ok,
            "debug": {
                "plan": plan,
                "results": results,
                "memory_updates": memory_updates,
            },
        }
