import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = "fb898be59e1de6ebc9b565f2d4019fc1"

if not TOKEN:
    print("❌ ERROR: No se encontró TRAVELPAYOUTS_TOKEN en .env")
    exit(1)

def buscar_vuelo_mas_barato(origen, destino, mes, moneda="BRL"):
    """
    Busca el vuelo más barato y genera enlace directo.
    """
    url = "https://api.travelpayouts.com/v2/prices/month-matrix"
    
    params = {
        "currency": moneda.lower(),
        "show_to_affiliates": "true",
        "origin": origen.upper(),
        "destination": destino.upper(),
        "month": mes.replace("-", ""),
        "token": TOKEN
    }
    
    print(f"\n📅 Buscando: {origen.upper()} → {destino.upper()} | {mes}")
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        
        if resp.status_code == 200:
            datos = resp.json()
            
            if datos.get("success") and datos.get("data"):
                vuelos = datos["data"]
                print(f"   ✅ {len(vuelos)} días con vuelos")
                
                vuelos_ordenados = sorted(vuelos, key=lambda x: x.get("value", 999999))
                
                print(f"\n   📊 TOP 3 MÁS BARATOS:")
                for i, v in enumerate(vuelos_ordenados[:3], 1):
                    print(f"   {i}. {v.get('depart_date')} - {moneda.upper()} {v.get('value'):.2f} ({v.get('gate', 'N/A')})")
                
                mas_barato = vuelos_ordenados[0]
                fecha = mas_barato.get("depart_date")
                precio = mas_barato.get("value")
                aerolinea = mas_barato.get("gate", "Consultar en el enlace")
                
                # Enlace CORREGIDO para Aviasales
                # Formato: https://aviasales.com/search/ORIGFECHADEST1
                enlace = f"https://aviasales.com/search/{origen.upper()}{fecha}{destino.upper()}1"
                
                # También generar enlace para la versión brasileña (PT-BR)
                enlace_br = f"https://www.aviasales.com.br/search/{origen.upper()}{fecha}{destino.upper()}1"
                
                return {
                    "fecha": fecha,
                    "precio": precio,
                    "moneda": moneda.upper(),
                    "aerolinea": aerolinea,
                    "enlace": enlace,
                    "enlace_br": enlace_br,
                    "dias_disponibles": len(vuelos),
                    "top3": vuelos_ordenados[:3]
                }
            else:
                print(f"   ⚠️ Sin datos para {mes}")
                return None
        elif resp.status_code == 403:
            print("   ❌ Token inválido")
            return None
        else:
            print(f"   ❌ Error HTTP {resp.status_code}")
            return None
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None

# ================================================
# PROGRAMA PRINCIPAL
# ================================================
if __name__ == "__main__":
    print("=" * 60)
    print("✈️  TRAVELPAYOUTS - VUELO MÁS BARATO")
    print("=" * 60)
    
    print("\n📝 Códigos IATA de ejemplo:")
    print("   Brasil: GRU, GIG, SSA, BSB, CNF, POA, REC")
    print("   Argentina: BUE, COR, MDZ, ROS")
    print("   España: MAD, BCN, AGP, VLC")
    
    print("\n" + "-" * 40)
    origen = input("🛫 Origen [GRU]: ").strip().upper() or "GRU"
    destino = input("🛬 Destino [SSA]: ").strip().upper() or "SSA"
    mes = input("📅 Mes [2026-05]: ").strip() or "2026-05"
    moneda = input("💵 Moneda [BRL]: ").strip().upper() or "BRL"
    
    print("\n" + "=" * 60)
    print("🔍 BUSCANDO...")
    print("=" * 60)
    
    resultado = buscar_vuelo_mas_barato(origen, destino, mes, moneda)
    
    if resultado:
        print("\n" + "=" * 60)
        print("🏆 RESULTADO FINAL")
        print("=" * 60)
        print(f"   ✈️  Ruta: {origen} → {destino}")
        print(f"   📅 Fecha más barata: {resultado['fecha']}")
        print(f"   💰 Precio: {resultado['moneda']} {resultado['precio']:.2f}")
        print(f"   🛩️  Aerolínea/Agente: {resultado['aerolinea']}")
        print(f"   📊 Días con vuelos: {resultado['dias_disponibles']}")
        
        print(f"\n   🔗 ENLACES DE COMPRA:")
        print(f"   Internacional: {resultado['enlace']}")
        print(f"   Brasil:        {resultado['enlace_br']}")
        
        print(f"\n   📋 Al abrir el enlace, deberías ver:")
        print(f"      Origen: {origen}")
        print(f"      Destino: {destino}")
        print(f"      Fecha: {resultado['fecha']}")
        print(f"      Precio aproximado: {resultado['moneda']} {resultado['precio']:.2f}")
        
        print(f"\n   📊 Otras opciones:")
        for i, v in enumerate(resultado['top3'][1:], 2):
            print(f"   {i}. {v.get('depart_date')} - {resultado['moneda']} {v.get('value'):.2f}")
        
        print("=" * 60)
    else:
        print("\n❌ No se encontraron vuelos para ese mes")
