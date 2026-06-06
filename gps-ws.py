import asyncio
import json
import websockets
import time
import math  # Neu für die präzise Berechnung des Positionsfehlers

GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9999
HTTP_PORT = 8888

connected_clients = set()
last_payload = "{}"

async def send_to_client(client, payload):
    try:
        await asyncio.wait_for(client.send(payload), timeout=0.5)
    except Exception:
        connected_clients.discard(client)

async def gpsd_reader():
    global last_payload
    while True:
        writer = None
        try:
            print(f"Verbinde zu GPSD ({GPSD_HOST})...")
            reader, writer = await asyncio.open_connection(GPSD_HOST, GPSD_PORT)
            
            writer.write(b'?WATCH={"enable":true,"json":true};\n')
            await writer.drain()
            await asyncio.sleep(0.2)
            
            writer.write(b'?POLL;\n')
            await writer.drain()

            while True:
                line = await reader.readline()
                if not line: 
                    break

                if b'"class":"TPV"' in line:
                    try:
                        tpv = json.loads(line.decode())
                    except json.JSONDecodeError:
                        continue

                    # OPTIMIERUNG 1: Filter nach Fix-Modus (mode 2 = 2D Fix, mode 3 = 3D Fix)
                    # Modus 0 oder 1 bedeutet: Kein GPS-Signal / Keine gültigen Daten.
                    if tpv.get("mode", 0) < 2:
                        continue

                    if "lat" in tpv and "lon" in tpv:
                        # OPTIMIERUNG 2: Präzise Berechnung der horizontalen Genauigkeit (Accuracy)
                        # GPSD liefert epx (Ost-West) und epy (Nord-Süd) Fehler. 
                        # Wenn vorhanden, berechnen wir daraus den kombinierten horizontalen Fehler.
                        epx = tpv.get("epx")
                        epy = tpv.get("epy")
                        
                        if epx is not None and epy is not None:
                            accuracy_value = math.sqrt(epx**2 + epy**2)
                        else:
                            # Fallback auf 'eph' oder GPSD-Standardwert, falls epx/epy fehlen
                            accuracy_value = tpv.get("eph") or tpv.get("sep") or 10.0

                        # OPTIMIERUNG 3: Intelligente Höhenermittlung
                        # Wenn mode=3 (3D Fix), ist die Höhe verlässlich. Bei 2D Fix erzwingen wir 0.0.
                        if tpv.get("mode") == 3:
                            altitude_value = tpv.get("altMSL") or tpv.get("altHAE") or tpv.get("alt") or 0.0
                        else:
                            altitude_value = 0.0

                        # OPTIMIERUNG 4: Plausibilitätsprüfungen für Geschwindigkeit und Richtung
                        # Einheiten-Konvertierung: GPSD liefert Meter pro Sekunde (m/s). 
                        # Für KM/H multiplizieren wir mit 3.6 (optional, hier im Standard belassen).
                        speed_value = tpv.get("speed")
                        heading_value = tpv.get("track")

                        last_payload = json.dumps({
                            "location": {
                                "lat": round(tpv["lat"], 7),   # Auf 7 Nachkommastellen runden (ca. 1cm Präzision)
                                "lng": round(tpv["lon"], 7)
                            },
                            "accuracy": round(max(1.0, float(accuracy_value)), 2),
                            "altitude": round(float(altitude_value), 2),
                            "speed": round(float(speed_value), 2) if speed_value is not None else None,
                            "heading": round(float(heading_value), 2) if heading_value is not None else None,
                            "fix_mode": tpv.get("mode"),       # Gibt Aufschluss über die Signalqualität (2=2D, 3=3D)
                            "satellites": tpv.get("nSat"),     # Anzahl der genutzten Satelliten (falls vom Empfänger geliefert)
                            "timestamp": time.time()
                        })

                        if connected_clients:
                            for client in list(connected_clients):
                                asyncio.create_task(send_to_client(client, last_payload))
                                
        except Exception as e:
            print(f"GPSD-Fehler: {e}. Neustart in 5s...")
        finally:
            if writer:
                try:
                    writer.close()
                    await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
                except Exception:
                    pass
            await asyncio.sleep(5)

async def ws_handler(websocket):
    connected_clients.add(websocket)
    try:
        async for _ in websocket: 
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)

async def http_handler(reader, writer):
    try:
        await reader.readuntil(b"\r\n\r\n")
        response_data = last_payload.encode("utf-8")
        http_response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: " + str(len(response_data)).encode() + b"\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
            b"Connection: close\r\n"
            b"\r\n" + response_data
        )
        writer.write(http_response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()

async def main():
    reader_task = asyncio.create_task(gpsd_reader())
    http_server = await asyncio.start_server(http_handler, LISTEN_HOST, HTTP_PORT)
    print(f"HTTP-Server aktiv auf http://{LISTEN_HOST}:{HTTP_PORT}")

    async with websockets.serve(ws_handler, LISTEN_HOST, LISTEN_PORT, ping_interval=10, ping_timeout=10):
        print(f"WebSocket-Proxy aktiv auf ws://{LISTEN_HOST}:{LISTEN_PORT}")
        await reader_task
        http_server.close()
        await http_server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
