import http.server
import json
import threading
import time
import os
import requests
import pifacedigitalio

CONFIG_FILE = "client_config.json"

def load_config():
    defaults = {
        "port": 8001,
        "server_url": "http://127.0.0.1:8000",
        "shared_api_key": "changeMe",
        "update_interval": 0.05
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

class PiFaceClientHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            if self.headers.get('X-API-KEY') != cfg['shared_api_key']:
                self.send_response(403); self.end_headers(); return
            
            in_val = pifacedigital.input_port.value
            out_val = pifacedigital.output_port.value
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"input": in_val, "output": out_val}).encode())
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
                print(f"Error processing command: {e}")
                self.send_response(500)
            self.end_headers()

    def _impulse(self, pin, duration):
        pifacedigital.output_pins[pin].turn_on()
        time.sleep(duration)
        pifacedigital.output_pins[pin].turn_off()

def input_monitor():
    last_state = 0
    server_url = f"{cfg['server_url']}/api/input"
    headers = {"X-API-KEY": cfg['shared_api_key'], "Content-Type": "application/json"}
    
    print(f"Input Monitor gestartet. Sende Events an {server_url}")

    while True:
        curr = pifacedigital.input_port.value
        for i in range(8):
            # Flankenerkennung: 0 -> 1 (Rising Edge)
            if (curr >> i) & 1 and not (last_state >> i) & 1:
                print(f"Input {i} erkannt -> Sende an Server...")
                try:
                    requests.post(
                        server_url, 
                        json={"pin": i, "state": 1}, 
                        headers=headers, 
                        timeout=1
                    )
                except Exception as e:
                    print(f"Fehler beim Senden des Input-Events: {e}")
        
        last_state = curr
        time.sleep(cfg['update_interval'])

if __name__ == "__main__":
    try:
        # Start Input Monitor in background
        threading.Thread(target=input_monitor, daemon=True).start()
        
        print(f"PiFace Client gestartet auf Port {cfg['port']}")
        http.server.HTTPServer(('', cfg['port']), PiFaceClientHandler).serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fataler Fehler: {e}")