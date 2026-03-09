import sys
import subprocess
import http.server
import urllib.parse
import json
import threading
import time
import os
import base64
from datetime import datetime

# --- Konfiguration laden ---
CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        "port": 8000,
        "user_name": "example",
        "user_pass": "1234",
        "impulse_duration": 2.0,
        "update_interval": 0.5,
        "log_file": "piface.log",
        "log_history_size": 20,
        "output_names": {},
        "input_names": {}
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                defaults.update(config)
                print("Konfiguration erfolgreich geladen.")
        except Exception as e:
            print(f"Fehler beim Laden der Config, nutze Defaults: {e}")
    return defaults

cfg = load_config()
AUTH_STR = base64.b64encode(f"{cfg['user_name']}:{cfg['user_pass']}".encode()).decode()

try:
    import pifacedigitalio
except ImportError:
    pifacedigitalio = None

# --- Hilfsfunktionen ---
def log_event(message):
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    try:
        with open(cfg['log_file'], "a") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"Fehler beim Schreiben ins Log: {e}")

def get_last_logs(n=20):
    if not os.path.exists(cfg['log_file']):
        return ["Keine Log-Einträge vorhanden."]
    try:
        with open(cfg['log_file'], "r") as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-n:]]
    except:
        return ["Fehler beim Lesen der Log-Datei."]

# --- UI Template (gekürzt zur Übersicht, JavaScript nutzt cfg Werte) ---
UI_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>PiFace Smart Control</title>
    <style>
        body {{ font-family: 'Segoe UI', Roboto, sans-serif; text-align: center; background: #f0f2f5; margin: 0; padding: 20px; color: #333; }}
        .container {{ max-width: 600px; margin: auto; background: white; padding: 25px; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
        .status-error {{ color: white; background: #d93025; padding: 12px; border-radius: 8px; margin-bottom: 20px; display: {error_display}; font-weight: bold; }}
        h2 {{ text-align: left; font-size: 1rem; color: #70757a; text-transform: uppercase; border-bottom: 2px solid #f1f3f4; padding-bottom: 8px; margin-top: 25px; }}
        .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 15px 0; }}
        .pin {{ padding: 15px 5px; border: 2px solid #e8eaed; border-radius: 12px; font-weight: bold; transition: all 0.2s ease; background: #fff; color: #5f6368; }}
        .clickable {{ cursor: pointer; border-color: #dadce0; color: #3c4043; }}
        .on {{ background: #34a853 !important; color: white !important; border-color: #1e8e3e !important; }}
        #log-container {{ text-align: left; background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 200px; overflow-y: auto; }}
        .log-entry {{ border-bottom: 1px solid #333; padding: 6px 0; font-size: 0.8rem; color: #aaa; }}
        .log-highlight {{ color: #ff9800 !important; font-weight: bold !important; }}
        .log-warn {{ color: #ff4444 !important; font-weight: bold !important; background: rgba(255,0,0,0.1); }}
        #info {{ margin-top: 20px; font-size: 0.8rem; color: #9aa0a6; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Haus-Steuerung</h1>
        <div class="status-error">Hardware-Fehler: PiFace nicht erkannt!</div>
        <div class="grid" id="out-grid"></div>
        <div class="grid" id="in-grid"></div>
        <div id="log-container">Lade Logbuch...</div>
        <p id="info">Initialisiere...</p>
    </div>
    <script>
        var outputNames = {output_names_json};
        var inputNames = {input_names_json};
        var logContainer = document.getElementById('log-container');
        for(var i=0; i<8; i++) {{
            var outName = (i in outputNames) ? outputNames[i] : 'OUT ' + i;
            document.getElementById('out-grid').innerHTML += '<div id="out-'+i+'" class="pin clickable" onclick="sendTrigger('+i+')">'+outName+'</div>';
            var inName = (i in inputNames) ? inputNames[i] : 'IN ' + i;
            document.getElementById('in-grid').innerHTML += '<div id="in-'+i+'" class="pin">'+inName+'</div>';
        }}
        function sendTrigger(bit) {{ fetch('/set?bit=' + bit); }}
        function fetchStatus() {{
            fetch('/status').then(r => r.json()).then(data => {{
                for(var i=0; i<8; i++) {{
                    document.getElementById('out-'+i).className = (data.output>>i)&1 ? 'pin clickable on' : 'pin clickable';
                    document.getElementById('in-'+i).className = (data.input>>i)&1 ? 'pin on' : 'pin';
                }}
                logContainer.innerHTML = data.logs.reverse().map(l => {{
                    var cl = "log-entry" + (l.includes(" EIN")?" log-highlight":"") + (l.includes("WARNUNG")?" log-warn":"");
                    return '<div class="'+cl+'">'+l+'</div>';
                }}).join('');
                document.getElementById('info').innerText = "Status: Online | IP: " + data.ip;
            }});
        }}
        setInterval(fetchStatus, {update_ms});
        fetchStatus();
    </script>
</body>
</html>
"""

class PiFaceWebHandler(http.server.BaseHTTPRequestHandler):
    pifacedigital = None
    def log_message(self, format, *args): return

    def check_auth(self):
        auth_header = self.headers.get('Authorization')
        if auth_header != f"Basic {AUTH_STR}":
            if auth_header: log_event(f"WARNUNG: Falsches Passwort von IP {self.client_address[0]}")
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="PiFace Control"')
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if not self.check_auth(): return
        if self.path == "/status":
            in_val = self.pifacedigital.input_port.value if self.pifacedigital else 0
            out_val = self.pifacedigital.output_port.value if self.pifacedigital else 0
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"input":in_val,"output":out_val,"ip":get_my_ip(),"logs":get_last_logs(cfg['log_history_size'])}).encode())
        elif self.path.startswith("/set"):
            bit = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["bit"][0])
            log_event(f"Web-UI: Befehl EIN für Ausgang {bit} empfangen.")
            threading.Thread(target=trigger_impulse, args=(bit,)).start()
            self.send_response(200); self.end_headers()
        else:
            log_event(f"Login: User {cfg['user_name']} (IP: {self.client_address[0]})")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(UI_TEMPLATE.format(
                error_display="none" if self.pifacedigital else "block",
                update_ms=int(cfg['update_interval']*1000),
                output_names_json=json.dumps(cfg.get('output_names', {})),
                input_names_json=json.dumps(cfg.get('input_names', {}))
            ).encode())

def trigger_impulse(bit):
    if not PiFaceWebHandler.pifacedigital: return
    PiFaceWebHandler.pifacedigital.output_pins[bit].turn_on()
    time.sleep(cfg['impulse_duration'])
    PiFaceWebHandler.pifacedigital.output_pins[bit].turn_off()
    log_event(f"System: Ausgang {bit} nach {cfg['impulse_duration']}s automatisch AUS.")

def input_monitor():
    if not PiFaceWebHandler.pifacedigital: return
    last_state = 0
    while True:
        curr = PiFaceWebHandler.pifacedigital.input_port.value
        for i in range(8):
            if (curr >> i) & 1 and not (last_state >> i) & 1:
                log_event(f"Hardware: Eingang {i} EIN.")
                threading.Thread(target=trigger_impulse, args=(i,)).start()
        last_state = curr
        time.sleep(0.05)

def get_my_ip():
    try: return subprocess.check_output("hostname -I", shell=True).decode('utf-8').strip().split()[0]
    except: return "127.0.0.1"

if __name__ == "__main__":
    try:
        PiFaceWebHandler.pifacedigital = pifacedigitalio.PiFaceDigital()
        threading.Thread(target=input_monitor, daemon=True).start()
        log_event("System gestartet - Hardware OK.")
    except Exception as e:
        log_event(f"System gestartet - Simulation ({e})")
    http.server.HTTPServer(('', cfg['port']), PiFaceWebHandler).serve_forever()
