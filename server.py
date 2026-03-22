import sys
import subprocess
import urllib.request
import requests
import ssl
import http.server
import urllib.parse
import json
import threading
import time
import os
import base64
from datetime import datetime

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
        "input_names": {},
        "input_actions": {},
        "heartbeat_url": None,
        "heartbeat_interval": 60,
        "log_filter_exclude": [
            "Heartbeat",
            "SSL-Verifizierung"
        ],
        "piface_client_url": "http://127.0.0.1:8001",
        "shared_api_key": "changeMe"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                defaults.update(config)
                print("Konfiguration erfolgreich geladen.")
        except json.JSONDecodeError as e:
            print(f"ACHTUNG: {CONFIG_FILE} enthält ungültiges JSON!")
            print(f"Fehler in Zeile {e.lineno}, Spalte {e.colno}: {e.msg}")
            print("HINWEIS: Es werden die Standardwerte verwendet.")
        except Exception as e:
            print(f"Fehler beim Laden der Config, nutze Defaults: {e}")
    return defaults

cfg = load_config()
AUTH_STR = base64.b64encode(f"{cfg['user_name']}:{cfg['user_pass']}".encode()).decode()

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

def get_last_logs(n=20, exclude_list=None):
    if not os.path.exists(cfg['log_file']):
        return ["Keine Log-Einträge vorhanden."]
    try:
        with open(cfg['log_file'], "r") as f:
            lines = f.readlines()

        # Use the passed exclude_list. If None, use the config default.
        current_excludes = exclude_list if exclude_list is not None else cfg.get('log_filter_exclude', [])
        if current_excludes:
            # Filter lines that contain any of the exclude strings
            filtered_lines = [
                line for line in lines
                if not any(exclude_str in line for exclude_str in current_excludes)
            ]
        else:
            filtered_lines = lines

        return [line.strip() for line in filtered_lines[-n:]]
    except:
        return ["Fehler beim Lesen der Log-Datei."]

def get_output_name(bit):
    return cfg['output_names'].get(str(bit), f"Ausgang {bit}")

def get_input_name(bit):
    return cfg['input_names'].get(str(bit), f"Eingang {bit}")

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
        .filter-grid {{ display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; margin-bottom: 20px; }}
        .filter-label {{ display: flex; align-items: center; gap: 5px; background: #f1f3f4; padding: 5px 10px; border-radius: 16px; font-size: 0.9rem; cursor: pointer; user-select: none; }}
        .filter-checkbox {{ accent-color: #34a853; }}
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
        <h2 id="log-filter-title" style="display: none;">Log-Filter</h2>
        <div id="filter-controls" class="filter-grid"></div>
        <p id="info">Initialisiere...</p>
    </div>
    <script>
        var outputNames = {output_names_json};
        var inputNames = {input_names_json};
        var defaultExcludes = {log_filter_json};
        var logContainer = document.getElementById('log-container');
        var filterContainer = document.getElementById('filter-controls');

        for(var i=0; i<8; i++) {{
            var outName = (i in outputNames) ? outputNames[i] : 'OUT ' + i;
            document.getElementById('out-grid').innerHTML += '<div id="out-'+i+'" class="pin clickable" onclick="sendTrigger('+i+')">'+outName+'</div>';
            var inName = (i in inputNames) ? inputNames[i] : 'IN ' + i;
            document.getElementById('in-grid').innerHTML += '<div id="in-'+i+'" class="pin clickable" onclick="simulateInput('+i+')">'+inName+'</div>';
        }}

        // Build filter UI
        if (defaultExcludes.length > 0) {{
            document.getElementById('log-filter-title').style.display = 'block';
            defaultExcludes.forEach(filter => {{
                filterContainer.innerHTML += `
                    <label class="filter-label">
                        <input type="checkbox" class="filter-checkbox" value="${{filter}}" onchange="fetchStatus()" checked>
                        ${{filter}}
                    </label>
                `;
            }});
        }}

        function getFilterQuery() {{
            var query = [];
            document.querySelectorAll('.filter-checkbox:checked').forEach(cb => {{
                query.push('exclude=' + encodeURIComponent(cb.value));
            }});
            return query.length > 0 ? '?' + query.join('&') : '';
        }}

        function sendTrigger(bit) {{ fetch('/set?bit=' + bit); }}
        function simulateInput(bit) {{ fetch('/simulate_input?bit=' + bit); }}
        function fetchStatus() {{
            fetch('/status' + getFilterQuery()).then(r => r.json()).then(data => {{
                for(var i=0; i<8; i++) {{
                    document.getElementById('out-'+i).className = (data.output>>i)&1 ? 'pin clickable on' : 'pin clickable';
                    document.getElementById('in-'+i).className = (data.input>>i)&1 ? 'pin on' : 'pin';
                }}
                logContainer.innerHTML = data.logs.reverse().map(l => {{
                    var cl = "log-entry" + (l.includes(" EIN")?" log-highlight":"") + (l.includes("WARNUNG")?" log-warn":"");
                    return '<div class="'+cl+'">'+l+'</div>';
                }}).join('');
                var clientStatus = data.client_ok ? '<span style="color:#34a853; font-weight:bold;">PiFace: Verbunden</span>' : '<span style="color:#d93025; font-weight:bold;">PiFace: Getrennt</span>';
                document.getElementById('info').innerHTML = "Server: Online | IP: " + data.ip + " | " + clientStatus;
            }});
        }}
        setInterval(fetchStatus, {update_ms});
        fetchStatus();
    </script>
</body>
</html>
"""

class PiFaceWebHandler(http.server.BaseHTTPRequestHandler):
    simulated_output_state = 0
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

    def do_POST(self):
        # Endpunkt für Input-Events vom Raspberry Pi
        if self.path == "/api/input":
            key = self.headers.get('X-API-KEY')
            if key != cfg['shared_api_key']:
                self.send_response(403)
                self.end_headers()
                return
            
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                bit = data.get('pin')
                state = data.get('state')
                if bit is not None and state == 1:
                    log_event(f"Hardware-Event: {get_input_name(bit)} EIN (via Client).")
                    threading.Thread(target=process_input_event, args=(bit,)).start()
                self.send_response(200)
            except Exception as e:
                log_event(f"Fehler beim Verarbeiten des Input-Events: {e}")
                self.send_response(400)
            self.end_headers()
            return

    def do_GET(self):
        if self.path == "/":
            client_status = "Disconnected"
            try:
                r = requests.get(
                    f"{cfg['piface_client_url']}/status", 
                    headers={"X-API-KEY": cfg['shared_api_key']}, 
                    timeout=1
                )
                if r.status_code == 200:
                    client_status = "Connected"
            except Exception:
                pass
            
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"PiFace: {client_status}".encode())
            return

        if not self.check_auth(): return
        if self.path.startswith("/status"):
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            exclude_list = query_params.get('exclude', [])

            # Status vom Client (Raspberry Pi) abfragen
            in_val = 0
            out_val = PiFaceWebHandler.simulated_output_state
            client_ok = False
            
            try:
                r = requests.get(
                    f"{cfg['piface_client_url']}/status", 
                    headers={"X-API-KEY": cfg['shared_api_key']}, 
                    timeout=1
                )
                if r.status_code == 200:
                    data = r.json()
                    in_val = data.get('input', 0)
                    out_val = data.get('output', 0)
                    client_ok = True
            except Exception:
                # Client nicht erreichbar, behalte Standardwerte oder Simulation
                pass

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"input":in_val,"output":out_val,"ip":get_my_ip(),"client_ok":client_ok,"logs":get_last_logs(cfg['log_history_size'], exclude_list=exclude_list)}).encode())
        elif self.path.startswith("/set"):
            bit = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["bit"][0])
            log_event(f"Web-UI: Befehl EIN für {get_output_name(bit)} empfangen.")
            threading.Thread(target=execute_impulse, args=(bit,)).start()
            self.send_response(200); self.end_headers()
        elif self.path.startswith("/simulate_input"):
            bit = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["bit"][0])
            log_event(f"Web-UI: Simulation für {get_input_name(bit)} empfangen.")
            threading.Thread(target=process_input_event, args=(bit,)).start()
            self.send_response(200); self.end_headers()
        else:
            log_event(f"Login: User {cfg['user_name']} (IP: {self.client_address[0]})")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(UI_TEMPLATE.format(
                error_display="none", # Fehleranzeige könnte man über Status-Check steuern
                update_ms=int(cfg['update_interval']*1000),
                output_names_json=json.dumps(cfg.get('output_names', {})),
                input_names_json=json.dumps(cfg.get('input_names', {})),
                log_filter_json=json.dumps(cfg.get('log_filter_exclude', []))
            ).encode())

def execute_impulse(bit, duration=None):
    actual_duration = duration if duration is not None else cfg['impulse_duration']
    output_name = get_output_name(bit)
    
    try:
        url = f"{cfg['piface_client_url']}/cmd"
        payload = {"action": "impulse", "pin": bit, "duration": actual_duration}
        headers = {"X-API-KEY": cfg['shared_api_key']}
        requests.post(url, json=payload, headers=headers, timeout=2)
        log_event(f"System: {output_name} nach Impuls ({actual_duration}s) wieder AUS.")
    except Exception as e:
        log_event(f"FEHLER: Konnte Befehl an Pi nicht senden: {e}")
        # Fallback Simulation lokal
        PiFaceWebHandler.simulated_output_state |= (1 << bit)
        time.sleep(actual_duration)
        PiFaceWebHandler.simulated_output_state &= ~(1 << bit)

def execute_toggle(bit):
    output_name = get_output_name(bit)

    try:
        url = f"{cfg['piface_client_url']}/cmd"
        payload = {"action": "toggle", "pin": bit}
        headers = {"X-API-KEY": cfg['shared_api_key']}
        # Toggle requires knowing current state, logic is better handled on client or by explicit ON/OFF. 
        # We send 'toggle' action to client.
        requests.post(url, json=payload, headers=headers, timeout=2)
        log_event(f"System: {output_name} umgeschaltet auf {'EIN' if new_state else 'AUS'}.")
    except Exception as e:
        # Simulation logic
        is_on = (PiFaceWebHandler.simulated_output_state >> bit) & 1
        if is_on:
            PiFaceWebHandler.simulated_output_state &= ~(1 << bit)
            log_event(f"Simulation: {output_name} umgeschaltet auf AUS.")
        else:
            PiFaceWebHandler.simulated_output_state |= (1 << bit)
            log_event(f"Simulation: {output_name} umgeschaltet auf EIN.")

def execute_webhook(action_config, context=None):
    if context is None:
        context = {}

    url = action_config.get('url')
    if not url:
        log_event("WARNUNG: Webhook-Aktion ohne URL konfiguriert.")
        return

    method = action_config.get('method', 'GET').upper()
    headers = action_config.get('headers', {})
    
    # Check if SSL verification should be disabled for this webhook
    verify_ssl = action_config.get("verify_ssl", True)
    timeout = action_config.get("timeout", 10)

    if not verify_ssl:
        log_event(f"WARNUNG: SSL-Verifizierung für Webhook an {url} ist deaktiviert.")

    log_event(f"System: Löse Webhook aus: {method} an {url}")
    try:
        request_args = {
            "method": method,
            "url": url,
            "headers": headers,
            "verify": verify_ssl,
            "timeout": timeout
        }

        payload = action_config.get('payload')
        attachment_config = action_config.get('attach_from_context')

        if attachment_config:
            # Multipart request (file upload)
            context_var = attachment_config.get('context_variable')
            if context_var not in context:
                log_event(f"FEHLER: Variable '{context_var}' für Dateianhang nicht im Kontext gefunden.")
                return

            file_data = context[context_var]
            form_field = attachment_config.get('form_field_name', 'file')
            filename = attachment_config.get('filename', 'upload')
            
            request_args["files"] = {form_field: (filename, file_data)}
            if payload:
                # For multipart, payload fields go into 'data'
                request_args["data"] = payload
        else:
            # Standard request
            if payload:
                # The 'json' parameter handles JSON serialization and sets the correct Content-Type header.
                request_args["json"] = payload

        response = requests.request(**request_args)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        log_event(f"System: Webhook erfolgreich ausgelöst (Status: {response.status_code}).")

        if action_config.get("store_response_as"):
            key = action_config["store_response_as"]
            context[key] = response.content
            log_event(f"System: Antwort des Webhooks im Kontext als '{key}' gespeichert ({len(response.content)} bytes).")

    except Exception as e:
        error_message = f"FEHLER: Webhook konnte nicht ausgelöst werden: {e}"
        # Check if the exception has a 'response' attribute (like requests.HTTPError)
        if hasattr(e, 'response') and e.response is not None:
            try:
                # Try to append the server's response body for more details
                error_message += f" | Server-Antwort: {e.response.text}"
            except:
                pass # Ignore if we can't get the text
        log_event(error_message)

def _execute_single_action(action, input_name, action_desc, context):
    action_type = action.get('type')
    log_event(f"System: Führe {action_desc} aus (Typ: {action_type}) für {input_name}.")

    if action_type == 'output':
        target = action.get('target')
        mode = action.get('mode', 'impulse')
        if target is None:
            log_event(f"WARNUNG: Fehlende 'target' Konfiguration für {action_desc} von {input_name}.")
            return
        if mode == 'impulse':
            duration = action.get('duration')
            execute_impulse(target, duration)
        elif mode == 'toggle':
            execute_toggle(target)
    elif action_type == 'webhook':
        execute_webhook(action, context)
    elif action_type == 'delay':
        duration = action.get('duration')
        if duration and isinstance(duration, (int, float)) and duration > 0:
            log_event(f"System: Warte für {duration} Sekunden...")
            time.sleep(duration)
        else:
            log_event(f"WARNUNG: Ungültige 'duration' für {action_desc} von {input_name}.")
    else:
        log_event(f"WARNUNG: Unbekannter Aktionstyp '{action_type}' für {action_desc} von {input_name}.")

def process_input_event(bit):
    action_config = cfg.get('input_actions', {}).get(str(bit))
    input_name = get_input_name(bit)

    if not action_config:
        log_event(f"System: Keine Aktion für {input_name} konfiguriert, nutze Standard (Impuls auf Ausgang {bit}).")
        execute_impulse(bit)
        return

    actions = action_config if isinstance(action_config, list) else [action_config]

    # Group actions by sequence_tag
    sequential_groups = {}
    parallel_actions = []

    for action in actions:
        tag = action.get('sequence_tag')
        if tag:
            if tag not in sequential_groups:
                sequential_groups[tag] = []
            sequential_groups[tag].append(action)
        else:
            parallel_actions.append(action)

    log_event(f"System: {input_name} hat {len(sequential_groups)} sequentielle Gruppe(n) und {len(parallel_actions)} parallele Aktion(en) ausgelöst.")

    # This function will be the target for our threads. It runs a sequence of actions.
    def _run_sequence(actions_list, tag, input_name):
        log_event(f"System: Starte sequentielle Ausführung für Gruppe '{tag}'.")
        context = {}  # Context is local to the sequence
        for i, action in enumerate(actions_list):
            action_desc = f"Aktion (Gruppe '{tag}', Schritt {i+1}/{len(actions_list)})"
            _execute_single_action(action, input_name, action_desc, context)

    # Start parallel actions
    for action in parallel_actions:
        # Each parallel action gets its own empty context, which is not used but keeps the signature consistent.
        threading.Thread(target=_execute_single_action, args=(action, input_name, "parallele Aktion", {})).start()

    # Start sequential groups
    for tag, actions_list in sequential_groups.items():
        threading.Thread(target=_run_sequence, args=(actions_list, tag, input_name)).start()

def get_my_ip():
    try: return subprocess.check_output("hostname -I", shell=True).decode('utf-8').strip().split()[0]
    except: return "127.0.0.1"

def heartbeat_monitor():
    url = cfg.get('heartbeat_url')
    if not url:
        return # Do nothing if no URL is configured

    interval = cfg.get('heartbeat_interval', 60)
    if not isinstance(interval, (int, float)) or interval <= 0:
        log_event(f"WARNUNG: Ungültiges Heartbeat-Intervall ({interval}). Deaktiviere Heartbeat.")
        return

    log_event(f"Heartbeat-Monitor für {url} gestartet (Intervall: {interval}s).")

    last_client_ok = True

    while True:
        # 1. Check: Ist der PiFace Client erreichbar?
        client_ok = False
        try:
            r = requests.get(
                f"{cfg['piface_client_url']}/status",
                headers={"X-API-KEY": cfg['shared_api_key']},
                timeout=5
            )
            if r.status_code == 200:
                client_ok = True
        except Exception:
            pass # Fehlerbehandlung erfolgt durch das Auslassen des Heartbeats
        
        if client_ok != last_client_ok:
            if client_ok:
                log_event("INFO: Verbindung zum PiFace Client wiederhergestellt.")
            else:
                log_event("WARNUNG: Verbindung zum PiFace Client unterbrochen!")
            last_client_ok = client_ok

        # 2. Nur wenn Client OK ist, senden wir den Heartbeat an Kuma
        if client_ok:
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    if not (200 <= response.status < 300):
                        log_event(f"WARNUNG: Heartbeat an {url} fehlgeschlagen (Status: {response.status}).")
            except Exception as e:
                log_event(f"FEHLER: Heartbeat an {url} konnte nicht gesendet werden: {e}")

        time.sleep(interval)

if __name__ == "__main__":
    try:
        log_event("Server gestartet (Controller Mode).")
    except Exception as e:
        log_event(f"Fehler beim Start: {e}")
    threading.Thread(target=heartbeat_monitor, daemon=True).start()
    http.server.HTTPServer(('', cfg['port']), PiFaceWebHandler).serve_forever()
