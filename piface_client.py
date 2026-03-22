import http.server
import json
import threading
import time
import os
import requests
import pifacedigitalio
from datetime import datetime

CONFIG_FILE = "client_config.json"

def load_config():
    defaults = {
        "port": 8001,
        "server_url": "http://127.0.0.1:8000",
        "shared_api_key": "changeMe",
        "update_interval": 0.05,
        "log_file": "client.log",
        "connection_check_interval": 60
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                defaults.update(json.load(f))
        except json.JSONDecodeError as e:
            print(f"Config Error: Invalid JSON in {CONFIG_FILE} at line {e.lineno}, col {e.colno}: {e.msg}")
        except Exception as e:
            print(f"Config Error: {e}")
    return defaults

cfg = load_config()
pifacedigital = pifacedigitalio.PiFaceDigital()
SERVER_CONNECTED = False

def log_event(message):
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    try:
        with open(cfg['log_file'], "a") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"Fehler beim Schreiben ins Log: {e}")

class PiFaceClientHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            status = "Connected" if SERVER_CONNECTED else "Disconnected"
            self.wfile.write(f"Server Connection: {status}".encode())
            return

        if self.path == "/status":
            if self.headers.get('X-API-KEY') != cfg['shared_api_key']:
                self.send_response(403); self.end_headers(); return
            
            in_val = pifacedigital.input_port.value
            out_val = pifacedigital.output_port.value
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"input": in_val, "output": out_val}).encode())
            return

        if self.path == "/logs":
            if self.headers.get('X-API-KEY') != cfg['shared_api_key']:
                self.send_response(403); self.end_headers(); return

            logs = []
            try:
                if os.path.exists(cfg['log_file']):
                    with open(cfg['log_file'], "r") as f:
                        logs = [line.strip() for line in f.readlines()[-50:]]
            except Exception as e:
                logs = [f"Fehler beim Lesen des Logs: {e}"]

            self.send_response(200); self.send_header("Content-type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"logs": logs}).encode())
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/cmd":
            if self.headers.get('X-API-KEY') != cfg['shared_api_key']:
                self.send_response(403); self.end_headers(); return

            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                action = data.get('action')
                pin = data.get('pin')
                
                if pin is not None and 0 <= pin <= 7:
                    log_event(f"CMD empfangen: {action} auf Pin {pin}")
                    if action == "impulse":
                        duration = data.get('duration', 1.0)
                        threading.Thread(target=self._impulse, args=(pin, duration)).start()
                    elif action == "toggle":
                        pifacedigital.output_pins[pin].toggle()
                    elif action == "set":
                        state = data.get('state', 0)
                        pifacedigital.output_pins[pin].value = state
                
                self.send_response(200)
            except Exception as e:
                log_event(f"Fehler bei Befehlsverarbeitung: {e}")
                self.send_response(500)
            self.end_headers()

    def _impulse(self, pin, duration):
        pifacedigital.output_pins[pin].turn_on()
        time.sleep(duration)
        pifacedigital.output_pins[pin].turn_off()

def connection_monitor():
    global SERVER_CONNECTED
    url = f"{cfg['server_url']}/"
    interval = cfg.get('connection_check_interval', 60)
    log_event(f"Verbindungs-Monitor gestartet (Intervall: {interval}s). Prüfe {url}")
    
    last_server_ok = True
    
    while True:
        server_ok = False
        try:
            requests.get(url, timeout=5)
            server_ok = True
        except Exception:
            pass
            
        SERVER_CONNECTED = server_ok
        
        if server_ok != last_server_ok:
            if server_ok:
                log_event("INFO: Verbindung zum Server wiederhergestellt.")
            else:
                log_event("WARNUNG: Verbindung zum Server unterbrochen!")
            last_server_ok = server_ok
            
        time.sleep(interval)

def input_monitor():
    last_state = 0
    server_url = f"{cfg['server_url']}/api/input"
    headers = {"X-API-KEY": cfg['shared_api_key'], "Content-Type": "application/json"}
    
    log_event(f"Input Monitor gestartet. Sende Events an {server_url}")

    while True:
        curr = pifacedigital.input_port.value
        for i in range(8):
            # Flankenerkennung: 0 -> 1 (Rising Edge)
            if (curr >> i) & 1 and not (last_state >> i) & 1:
                log_event(f"Hardware-Input {i} erkannt -> Sende an Server...")
                try:
                    requests.post(
                        server_url, 
                        json={"pin": i, "state": 1}, 
                        headers=headers, 
                        timeout=1
                    )
                    log_event(f"Event für Input {i} erfolgreich an Server gesendet.")
                except Exception as e:
                    log_event(f"FEHLER beim Senden an Server: {e}")
        
        last_state = curr
        time.sleep(cfg['update_interval'])

if __name__ == "__main__":
    try:
        # Start Input Monitor in background
        threading.Thread(target=input_monitor, daemon=True).start()
        threading.Thread(target=connection_monitor, daemon=True).start()
        
        log_event(f"PiFace Client gestartet auf Port {cfg['port']}")
        http.server.HTTPServer(('', cfg['port']), PiFaceClientHandler).serve_forever()
    except KeyboardInterrupt:
        pass
    except PermissionError:
        log_event(f"Fataler Fehler: Zugriff auf Port {cfg['port']} verweigert. Für Ports < 1024 werden Root-Rechte benötigt (sudo).")
    except Exception as e:
        log_event(f"Fataler Fehler: {e}")