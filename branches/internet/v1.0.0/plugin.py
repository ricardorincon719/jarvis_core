"""
Plugin INTERNET - Acciones con internet (viajes, vuelos, clima, etc.)
"""

import requests
import os
import re
from datetime import datetime, timedelta

# Cargar variables de entorno desde .env manualmente (sin dependencia dotenv)
def cargar_env():
    """Carga variables de entorno desde archivo .env"""
    env_paths = [
        os.path.join(os.path.dirname(__file__), '..', '.env'),
        os.path.join(os.path.dirname(__file__), '.env'),
        '.env'
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip().strip('"').strip("'")
            break

cargar_env()

NAME = "internet"
VERSION = "v2.0.0"
DESCRIPTION = "Acciones con internet (vuelos Google Flights, clima, noticias, compras)"
TRIGGERS = ["clima", "tiempo", "vuelo", "vuelos", "viaje", "viajar", "comprar", "pedir", "noticias", "avión", "avion", "aeropuerto", "pasaje", "pasajes"]

# Configuración APIs
SERPAPI_KEY = "1123df78ec275d724713944cb9ce935c5700deeed7aae365d34a0b64f300bbf3"

def can_handle(prompt):
    """Verifica si el plugin puede manejar la solicitud"""
    prompt_lower = prompt.lower()
    return any(keyword in prompt_lower for keyword in TRIGGERS)

def buscar_vuelos_google(origen, destino, fecha_ida, fecha_vuelta=None, moneda="BRL"):
    """
    Busca vuelos en Google Flights vía SerpApi.
    Retorna una lista de vuelos con todos los detalles.
    """
    if not SERPAPI_KEY:
        return None
    
    url = "https://serpapi.com/search"
    
    params = {
        "engine": "google_flights",
        "departure_id": origen.upper(),
        "arrival_id": destino.upper(),
        "outbound_date": fecha_ida,
        "currency": moneda.upper(),
        "hl": "pt",
        "gl": "br",
        "api_key": SERPAPI_KEY
    }
    
    if fecha_vuelta:
        params["return_date"] = fecha_vuelta
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        
        if resp.status_code == 200:
            datos = resp.json()
            
            if "best_flights" in datos:
                vuelos = datos["best_flights"]
                resultados = []
                
                for vuelo in vuelos[:3]:  # Top 3
                    precio = vuelo.get("price", 0)
                    duracion = vuelo.get("total_duration", 0)
                    
                    tramos = vuelo.get("flights", [])
                    primer_tramo = tramos[0] if tramos else {}
                    ultimo_tramo = tramos[-1] if tramos else {}
                    
                    aerolinea = primer_tramo.get("airline", "N/A")
                    num_vuelo = primer_tramo.get("flight_number", "")
                    salida = primer_tramo.get("departure_airport", {}).get("time", "N/A")
                    llegada = ultimo_tramo.get("arrival_airport", {}).get("time", "N/A")
                    escalas = len(tramos) - 1
                    avion = primer_tramo.get("airplane", "")
                    clase = primer_tramo.get("travel_class", "Económica")
                    
                    # Enlace directo a Google Flights
                    enlace = f"https://www.google.com/travel/flights?q=Vuelos+de+{origen}+a+{destino}+el+{fecha_ida}"
                    if fecha_vuelta:
                        enlace += f"&return_date={fecha_vuelta}"
                    
                    resultados.append({
                        "aerolinea": aerolinea,
                        "num_vuelo": num_vuelo,
                        "precio": precio,
                        "duracion": duracion,
                        "salida": salida,
                        "llegada": llegada,
                        "escalas": escalas,
                        "avion": avion,
                        "clase": clase,
                        "enlace": enlace
                    })
                
                return resultados
        return None
    except Exception:
        return None

def extraer_parametros_vuelo(prompt):
    """
    Extrae origen, destino, fecha y duración del prompt del usuario.
    """
    prompt_lower = prompt.lower()
    
    # Mapeo de nombres comunes a códigos IATA
    aeropuertos = {
        # Brasil
        "são paulo": "GRU", "sao paulo": "GRU", "guarulhos": "GRU",
        "río de janeiro": "GIG", "rio de janeiro": "GIG", "rio": "GIG",
        "salvador": "SSA", "brasilia": "BSB", "belo horizonte": "CNF",
        "porto alegre": "POA", "recife": "REC", "curitiba": "CWB",
        "fortaleza": "FOR", "manaus": "MAO", "florianópolis": "FLN",
        "córdoba": "COR", "cordoba": "COR",
        # Argentina
        "buenos aires": "BUE", "mendoza": "MDZ", "rosario": "ROS",
        # España
        "madrid": "MAD", "barcelona": "BCN", "málaga": "AGP",
        "malaga": "AGP", "valencia": "VLC", "sevilla": "SVQ",
        "palma": "PMI", "bilbao": "BIO",
        # Otros
        "londres": "LON", "parís": "PAR", "paris": "PAR",
        "nueva york": "NYC", "miami": "MIA", "dubai": "DXB",
        "lisboa": "LIS", "oporto": "OPO", "tokio": "TYO",
        "santiago": "SCL", "lima": "LIM", "bogotá": "BOG"
    }
    
    # Mapeo de meses
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
    }
    
    origen = None
    destino = None
    fecha_ida = None
    fecha_vuelta = None
    
    # Detectar año
    años = re.findall(r'20\d{2}', prompt)
    año = años[0] if años else str(datetime.now().year)
    
    # Buscar origen y destino por nombres conocidos
    for nombre, codigo in aeropuertos.items():
        if nombre in prompt_lower:
            if origen is None:
                origen = codigo
            elif destino is None:
                destino = codigo
    
    # Si no encuentra por nombre, buscar códigos IATA
    if origen is None or destino is None:
        codigos = re.findall(r'\b[A-Z]{3}\b', prompt.upper())
        if len(codigos) >= 2:
            if origen is None:
                origen = codigos[0]
            if destino is None:
                destino = codigos[1]
        elif len(codigos) == 1 and origen is None:
            origen = codigos[0]
    
    # Detectar mes y construir fecha de ida
    for nombre_mes, numero_mes in meses.items():
        if nombre_mes in prompt_lower:
            dia = "01"  # Default: primer día del mes
            fecha_ida = f"{año}-{numero_mes}-{dia}"
            break
    
    # Si no hay mes, usar mes actual + 1
    if fecha_ida is None:
        ahora = datetime.now()
        mes_siguiente = (ahora.month % 12) + 1
        año_mes = ahora.year if mes_siguiente > 1 else ahora.year + 1
        fecha_ida = f"{año_mes}-{mes_siguiente:02d}-01"
    
    # Detectar duración de estancia para fecha de vuelta
    duracion_match = re.search(r'(\d+)\s*(días|dias|día|dia|semanas|semana)', prompt_lower)
    if duracion_match:
        dias = int(duracion_match.group(1))
        if "semana" in duracion_match.group(2):
            dias *= 7
        
        fecha_obj = datetime.strptime(fecha_ida, "%Y-%m-%d")
        fecha_vuelta_obj = fecha_obj + timedelta(days=dias)
        fecha_vuelta = fecha_vuelta_obj.strftime("%Y-%m-%d")
    else:
        # Default: 7 días de estancia
        fecha_obj = datetime.strptime(fecha_ida, "%Y-%m-%d")
        fecha_vuelta_obj = fecha_obj + timedelta(days=7)
        fecha_vuelta = fecha_vuelta_obj.strftime("%Y-%m-%d")
    
    return origen, destino, fecha_ida, fecha_vuelta

def handle(prompt):
    """
    Maneja las solicitudes del usuario.
    Retorna un diccionario con 'respuesta' y 'cerebro'.
    """
    prompt_lower = prompt.lower()
    
    # --- CLIMA ---
    if any(word in prompt_lower for word in ["clima", "tiempo", "temperatura"]):
        ciudad = "Córdoba"
        if "en" in prompt_lower:
            partes = prompt_lower.split("en")
            if len(partes) > 1:
                ciudad = partes[-1].strip().title()
        
        return {
            'respuesta': f"🌤️ Clima en {ciudad}: 24°C, parcialmente nublado. (API por implementar)",
            'cerebro': NAME
        }
    
    # --- VUELOS ---
    if any(word in prompt_lower for word in ["vuelo", "vuelos", "viaje", "viajar", "avión", "avion", "pasaje", "pasajes"]):
        
        if not SERPAPI_KEY:
            return {
                'respuesta': (
                    "✈️ Para buscar vuelos necesito configurar SerpApi.\n\n"
                    "📋 Pasos:\n"
                    "1. Ve a https://serpapi.com\n"
                    "2. Regístrate y obtén tu API Key\n"
                    "3. Agrega esta línea a tu archivo .env:\n"
                    "   SERPAPI_KEY=tu-api-key-aqui\n"
                    "4. Reinicia el sistema"
                ),
                'cerebro': NAME
            }
        
        # Extraer parámetros
        origen, destino, fecha_ida, fecha_vuelta = extraer_parametros_vuelo(prompt)
        
        if origen is None or destino is None:
            return {
                'respuesta': (
                    "✈️ Para buscar vuelos necesito:\n"
                    "   • Ciudad de origen (ej: São Paulo, Madrid)\n"
                    "   • Ciudad de destino (ej: Salvador, Barcelona)\n"
                    "   • Mes (opcional, ej: septiembre)\n"
                    "   • Duración (opcional, ej: 7 días)\n\n"
                    "📝 Ejemplos:\n"
                    "   'vuelo barato de São Paulo a Córdoba en junio'\n"
                    "   'vuelo GRU a COR en septiembre por 10 días'"
                ),
                'cerebro': NAME
            }
        
        # Buscar vuelos
        resultados = buscar_vuelos_google(origen, destino, fecha_ida, fecha_vuelta)
        
        if resultados and len(resultados) > 0:
            # Formatear respuesta
            respuesta = f"✈️ Vuelos {origen} → {destino}\n\n"
            respuesta += f"📅 Ida: {fecha_ida}"
            if fecha_vuelta:
                respuesta += f" | Vuelta: {fecha_vuelta}"
            respuesta += f"\n\n"
            
            for i, v in enumerate(resultados, 1):
                escalas_txt = "directo" if v["escalas"] == 0 else f"{v['escalas']} escala(s)"
                respuesta += (
                    f"{i}. {v['aerolinea']} {v['num_vuelo']}\n"
                    f"   💰 BRL {v['precio']:.2f} | ⏱️ {v['duracion']} min | ✈️ {escalas_txt}\n"
                    f"   🛫 {v['salida']} → 🛬 {v['llegada']}\n"
                    f"   🔗 <a href='{v['enlace']}' target='_blank'>Abrir en Google Flights</a>\n\n"
                )
            
            respuesta += "💡 Precios en tiempo real de Google Flights. Abre el enlace para comprar."
            
            return {
                'respuesta': respuesta,
                'cerebro': NAME
            }
        else:
            return {
                'respuesta': (
                    f"❌ No encontré vuelos de {origen} a {destino} para {fecha_ida}.\n\n"
                    f"💡 Sugerencias:\n"
                    f"   • Prueba con fechas más cercanas\n"
                    f"   • Verifica los códigos IATA (ej: GRU, SSA, MAD, BCN)\n"
                    f"   • Prueba una ruta más popular"
                ),
                'cerebro': NAME
            }
    
    # --- NOTICIAS (placeholder) ---
    if "noticias" in prompt_lower:
        return {
            'respuesta': "📰 Función de noticias en desarrollo.",
            'cerebro': NAME
        }
    
    # --- DEFAULT ---
    return {
        'respuesta': "🌐 Funciones disponibles: clima, vuelos. Prueba: 'busca vuelos a Córdoba en junio'",
        'cerebro': NAME
    }
