"""
Plugin HARDWARE - Control real de hardware
"""

import subprocess
import json

NAME = "hardware"
VERSION = "v1.0.0"
DESCRIPTION = "Control de hardware local (linterna, batería, vibración, biometría, sistemas)"
TRIGGERS = ["linterna", "batería", "bateria", "reporte", "sistemas", "vibrar", "huella", "biometría", "energía"]

def can_handle(prompt):
    prompt_lower = prompt.lower()
    return any(keyword in prompt_lower for keyword in TRIGGERS)

def handle(prompt):
    prompt_lower = prompt.lower()
    
    # ========== LINTERNA ==========
    if "linterna" in prompt_lower:
        if any(x in prompt_lower for x in ['encender', 'prender', 'activar', 'on']):
            subprocess.run(['termux-torch', 'on'])
            return {
                'respuesta': "Sistemas de iluminación activados, señor.",
                'cerebro': NAME
            }
        else:
            subprocess.run(['termux-torch', 'off'])
            return {
                'respuesta': "Sistemas de iluminación desactivados, señor.",
                'cerebro': NAME
            }
    
# ========== BATERÍA ==========
    if "batería" in prompt_lower or "bateria" in prompt_lower or "energía" in prompt_lower:
        porcentaje = 0
        estado_texto = "desconocido"
    
    # Opción 1: intentar con termux-battery-status
    try:
        result = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout:
            bat = json.loads(result.stdout)
            porcentaje = bat.get('percentage', 0)
            estado = bat.get('status', 'unknown')
            estado_texto = "cargando" if estado == 'CHARGING' else "descargando" if estado == 'DISCHARGING' else "conectado"
        else:
            raise Exception("termux-battery-status no respondió")
    except:
        # Opción 2: fallback con dumpsys
        try:
            import re
            result = subprocess.run(['/system/bin/dumpsys', 'battery'], capture_output=True, text=True, timeout=5)
            level_match = re.search(r'level:\s+(\d+)', result.stdout)
            status_match = re.search(r'status:\s+(\d+)', result.stdout)
            
            if level_match:
                porcentaje = int(level_match.group(1))
            
            if status_match:
                status_code = int(status_match.group(1))
                # status: 1=unknown, 2=charging, 3=discharging, 4=not charging, 5=full
                if status_code == 2:
                    estado_texto = "cargando"
                elif status_code == 3:
                    estado_texto = "descargando"
                elif status_code == 5:
                    estado_texto = "completa"
                else:
                    estado_texto = "conectado"
        except Exception as e:
            return {'respuesta': f"Error obteniendo batería: {e}", 'cerebro': NAME}
    
    return {
        'respuesta': f"Energía al {porcentaje}%. Estado: {estado_texto}.",
        'cerebro': NAME
    }
    
    # ========== VIBRACIÓN ==========
    if "vibrar" in prompt_lower:
        subprocess.run(['termux-vibrate', '-d', '1000'])
        return {'respuesta': "Alerta táctil activada.", 'cerebro': NAME}
    
    # ========== BIOMETRÍA ==========
    if "huella" in prompt_lower or "biometría" in prompt_lower:
        try:
            result = subprocess.run(['termux-fingerprint'], capture_output=True, text=True, timeout=15)
            if 'AUTH_RESULT_SUCCESS' in result.stdout:
                return {'respuesta': "Identificación biométrica exitosa. Bienvenido.", 'cerebro': NAME}
            return {'respuesta': "Identificación fallida.", 'cerebro': NAME}
        except:
            return {'respuesta': "Sensor de huella no responde.", 'cerebro': NAME}
    
    return {'respuesta': "Comando no reconocido.", 'cerebro': NAME}
