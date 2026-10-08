#!/usr/bin/env python3
"""Erzeugt node-red/esp-sync-import.json aus einem Node-RED-Export (flows.json).

Aufruf: python3 build_import.py flows.json esp-sync-import.json
"""
import copy
import json
import secrets
import sys

fl = json.load(open(sys.argv[1]))
byid = {n["id"]: n for n in fl}
tabs = {n["label"]: n["id"] for n in fl if n["type"] == "tab"}
HZ = tabs["Heizung"]
BROKER = "cf0cd411e9941005"           # 192.168.178.51
SOLL_UI = "510604c4c3752aa3"          # ui_numeric "Temperatur Soll"
VORLAUF_UI = "ceff669ab06c0527"       # ui_numeric "Vorlauftemperatur"
HEIZUNG_SW = "ecaa7d3f46b50fd3"       # ui_switch "Heizung AN/AUS"
AUTO_SW = "ef91ebd3d9cbb1cb"          # ui_switch "Automatik Betrieb"

def nid():
    return secrets.token_hex(8)

new, changed = [], {}

def mod(i):
    if i not in changed:
        changed[i] = copy.deepcopy(byid[i])
    return changed[i]

TAB = nid()
new.append({"id": TAB, "type": "tab", "label": "ESP Sync", "disabled": False, "info":
    "Hält Soll, Vorlaufstufe und Heizung AN/AUS zwischen ESP (Taster) und Dashboard synchron.\n"
    "Der ESP ist führend: er speichert die Werte und meldet sie auf home/vaillant/esp1/state/*.\n"
    "Änderungen im Dashboard gehen als home/vaillant/esp1/cmd/* an den ESP.\n"
    "Im Automatikbetrieb sind Soll und Vorlauf gesperrt (Dashboard und Taster)."})

def node(**kw):
    n = {"id": nid(), "z": TAB, "wires": []}
    n.update(kw)
    new.append(n)
    return n

def mqtt_in(topic, name, x, y):
    return node(type="mqtt in", name=name, topic=topic, qos="1", datatype="utf8", broker=BROKER,
                nl=False, rap=True, rh=0, inputs=0, x=x, y=y, wires=[[]])

def mqtt_out(topic, name, x, y, retain=False):
    return node(type="mqtt out", name=name, topic=topic, qos="1", retain="true" if retain else "false",
                respTopic="", contentType="", userProps="", correl="", expiry="", broker=BROKER, x=x, y=y)

def fn(name, code, x, y, outputs=1, z=None):
    return node(type="function", name=name, func=code, outputs=outputs, timeout=0, noerr=0,
                initialize="", finalize="", libs=[], x=x, y=y, wires=[[] for _ in range(outputs)],
                **({"z": z} if z else {}))

def wire(src, dst, port=0):
    src["wires"][port].append(dst["id"])

def link(out_node, in_node):
    out_node.setdefault("links", []).append(in_node["id"])
    in_node.setdefault("links", []).append(out_node["id"])

def link_in(name, x, y, z=None, target=None):
    n = node(type="link in", name=name, links=[], x=x, y=y, wires=[[target] if target else []],
             **({"z": z} if z else {}))
    return n

def link_out(name, x, y, z=None):
    return node(type="link out", name=name, mode="link", links=[], x=x, y=y, **({"z": z} if z else {}))

def hz_input(name, target_id):
    """Link-In im Tab Heizung, der direkt in ein vorhandenes Dashboard-Element führt."""
    t = byid[target_id]
    return link_in(name, t["x"] - 200, t["y"] + 40, z=HZ, target=target_id)

def hz_output(name, source_id):
    """Link-Out im Tab Heizung, an den Ausgang eines vorhandenen Dashboard-Elements gehängt."""
    s = byid[source_id]
    lo = link_out(name, s["x"] + 230, s["y"] - 30, z=HZ)
    mod(source_id)["wires"][0].append(lo["id"])
    return lo

node(type="comment", name="ESP -> Dashboard (state/*)", info="", x=170, y=40)
node(type="comment", name="Dashboard -> ESP (cmd/*)", info="", x=170, y=300)
node(type="comment", name="Automatikbetrieb -> ESP und Sperre im Dashboard", info="", x=230, y=500)

# ---------------- ESP -> Dashboard ----------------
soll_in = hz_input("ESP Soll", SOLL_UI)
vl_in = hz_input("ESP Vorlauf", VORLAUF_UI)
sw_in = hz_input("ESP Ein/Aus", HEIZUNG_SW)

i1 = mqtt_in("home/vaillant/esp1/state/setpoint", "ESP Soll", 170, 100)
f1 = fn("ESP Soll", """// Wert vom ESP merken, damit er nicht als Befehl zurückgeht
const v = Number(msg.payload);
if (isNaN(v)) return null;
flow.set('espSetpoint', v);
if (flow.get('auto') === true) return null;   // im Automatikbetrieb zeigt das Dashboard das berechnete Ziel
return { payload: v, topic: 'setTarget', enabled: true };""", 410, 100)
o1 = link_out("-> Temperatur Soll", 640, 100)
wire(i1, f1); wire(f1, o1); link(o1, soll_in)

i2 = mqtt_in("home/vaillant/esp1/state/vorlauf", "ESP Vorlauf", 170, 160)
f2 = fn("ESP Vorlauf", """const v = parseInt(msg.payload, 10);
if (isNaN(v)) return null;
flow.set('espStage', v);
if (flow.get('auto') === true) return null;   // im Automatikbetrieb gilt die Stufenregelung
return { payload: v, topic: 'setVorlauf', enabled: true };""", 410, 160)
o2 = link_out("-> Vorlauftemperatur", 650, 160)
wire(i2, f2); wire(f2, o2); link(o2, vl_in)

i3 = mqtt_in("home/vaillant/esp1/state/enabled", "ESP Ein/Aus", 170, 220)
f3 = fn("ESP Ein/Aus", """// true = Heizung freigegeben (so wertet die Heater logic setWindow aus)
let on;
if (msg.payload === 'on') on = true;
else if (msg.payload === 'off') on = false;
else return null;
flow.set('espEnabled', on);
return { payload: on, topic: 'setWindow' };""", 410, 220)
o3 = link_out("-> Heizung AN/AUS", 650, 220)
wire(i3, f3); wire(f3, o3); link(o3, sw_in)

# ---------------- Dashboard -> ESP ----------------
d1 = link_in("Dashboard Soll", 190, 360)
g1 = fn("Soll an ESP", """// Merken, was das Dashboard gerade zeigt (für die Sperre)
flow.set('uiSetpoint', { payload: msg.payload, topic: msg.topic });
if (flow.get('auto') === true) return null;   // gesperrt
const v = Number(msg.payload);
if (isNaN(v)) return null;
const esp = flow.get('espSetpoint');
if (esp !== undefined && Math.abs(esp - v) < 0.01) return null;   // kein Echo
return { payload: String(v) };""", 420, 360)
c1 = mqtt_out("home/vaillant/esp1/cmd/setpoint", "an ESP: Soll", 680, 360)
wire(d1, g1); wire(g1, c1); link(hz_output("an ESP Soll", SOLL_UI), d1)

d2 = link_in("Dashboard Vorlauf", 200, 420)
g2 = fn("Vorlauf an ESP", """flow.set('uiStage', msg.payload);
if (flow.get('auto') === true) return null;   // gesperrt
const v = parseInt(msg.payload, 10);
if (isNaN(v)) return null;
if (flow.get('espStage') === v) return null;   // kein Echo
return { payload: String(v) };""", 430, 420)
c2 = mqtt_out("home/vaillant/esp1/cmd/vorlauf", "an ESP: Vorlauf", 690, 420)
wire(d2, g2); wire(g2, c2); link(hz_output("an ESP Vorlauf", VORLAUF_UI), d2)

d3 = link_in("Dashboard Ein/Aus", 200, 460)
g3 = fn("Ein/Aus an ESP", """// true = Heizung freigegeben
if (typeof msg.payload !== 'boolean') return null;
if (flow.get('espEnabled') === msg.payload) return null;   // kein Echo
return { payload: msg.payload ? 'on' : 'off' };""", 430, 460)
c3 = mqtt_out("home/vaillant/esp1/cmd/enabled", "an ESP: Ein/Aus", 690, 460)
wire(d3, g3); wire(g3, c3); link(hz_output("an ESP Ein/Aus", HEIZUNG_SW), d3)

# ---------------- Automatikbetrieb ----------------
d4 = link_in("Automatik Betrieb", 200, 560)
g4 = fn("Automatik", """// true = Automatikbetrieb (so wertet die autoMode-Funktion den Schalter aus)
if (typeof msg.payload !== 'boolean') return null;
const auto = msg.payload;
const was = flow.get('auto');
flow.set('auto', auto);
const toEsp = { payload: auto ? 'on' : 'off' };
if (was === auto) return [toEsp, null, null];
if (auto) {
    // Sperren: aktuellen Wert unverändert mitschicken, damit nichts Neues ausgelöst wird
    const sp = flow.get('uiSetpoint');
    const st = flow.get('uiStage');
    return [toEsp,
            sp ? { payload: sp.payload, topic: sp.topic, enabled: false } : null,
            st !== undefined ? { payload: st, topic: 'setVorlauf', enabled: false } : null];
}
// Entsperren: der ESP meldet daraufhin seine eigenen Werte (mit enabled: true)
return [toEsp, null, null];""", 420, 560, outputs=3)
c4 = mqtt_out("home/vaillant/esp1/automode", "an ESP: Automatik", 700, 540, retain=True)
o4a = link_out("-> Temperatur Soll", 690, 580)
o4b = link_out("-> Vorlauftemperatur", 700, 620)
wire(d4, g4); wire(g4, c4, 0); wire(g4, o4a, 1); wire(g4, o4b, 2)
link(o4a, soll_in); link(o4b, vl_in)
link(hz_output("an ESP Automatik", AUTO_SW), d4)

# ---------------- vorhandene Knoten anpassen ----------------
# Schalter: AN sendet künftig true (Logik unverändert, nur die Anzeige stimmt dann)
for sw in (HEIZUNG_SW, AUTO_SW):
    m = mod(sw)
    m.update({"onvalue": "true", "onvalueType": "bool", "offvalue": "false", "offvalueType": "bool"})
# Alte Taster-Eingänge deaktivieren (die Taster wirken jetzt im ESP)
for t in ("TempUp", "TempDown", "VorlaufUp", "VorlaufDown", "heater"):
    for n in fl:
        if n["type"] == "mqtt in" and n.get("topic") == "home/vaillant/esp1/" + t:
            mod(n["id"])["d"] = True
# Zustand für den ESP behalten (retain)
for i in ("7ecca48d346980a5", "faa1afea11c4c221"):   # heaterOn/Off, Vorlauftemp
    mod(i)["retain"] = "true"
# Start-Injects für Soll, Vorlauf und Heizung AN/AUS abschalten: der ESP ist führend und
# meldet seine Werte beim Start über state/* (retained). Sonst würde jeder Node-RED-Start
# die Werte im ESP überschreiben. Die Injects am Automatik-Schalter bleiben aktiv.
for n in fl:
    if n["type"] == "inject" and n.get("z") == HZ and n.get("once") and \
            {SOLL_UI, VORLAUF_UI, HEIZUNG_SW} & {w for o in n.get("wires", []) for w in o}:
        mod(n["id"])["d"] = True
# Test-Inject -1 °C in der Stufenregelung abschalten
mod("temp_in")["d"] = True

out = new + list(changed.values())
json.dump(out, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
print(f"{len(new)} neue Knoten, {len(changed)} geänderte Knoten")
