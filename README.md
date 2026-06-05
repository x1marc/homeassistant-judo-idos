# JUDO i-dos — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/x1marc/homeassistant-judo-idos/actions/workflows/validate.yml/badge.svg)](https://github.com/x1marc/homeassistant-judo-idos/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

HACS-kompatible Custom Integration, die Verbrauchs- und Statusdaten eines
**JUDO i-dos** Dosiergeräts über die JUDO-Cloud (OptiSoft-Relay) in Home
Assistant einbindet.

> ✅ Funktioniert **ohne** separates *Connectivity Module* — das i-dos
> verbindet sich selbst per WLAN mit der JUDO-Cloud.

---

## Features

- 🔐 Einrichtung komplett über die HA-Oberfläche (Config Flow)
- ⏱️ Einstellbares Abrufintervall (5–60 Minuten)
- 📊 28 Sensoren: Wasserverbrauch (Tag/Woche/Monat/Jahr), Durchfluss,
  Wasserhärte, Minerallösung (Vorrat/Reichweite/Typ), Gerätestatus,
  Wartungsdaten u. a.
- 🎛️ Dosiermenge umschaltbar (minimal/normal/maximal) per Select-Entität
- 🔄 Automatischer Login + Connect bei jedem Abruf (Token ist kurzlebig)
- 🌐 DNS-Auflösung mit fester IP als Fallback (überlebt einen Server-Umzug)

---

## Sensoren

| Sensor | Einheit | Beschreibung |
|---|---|---|
| Gesamtwassermenge | m³ / L | Gesamtverbrauch (Total-Increasing) |
| Verbrauch heute | L | Summe des laufenden Tages |
| Verbrauch Woche | L | Summe der laufenden Woche (Mo–So) |
| Verbrauch Monat | m³ / L | Summe des laufenden Monats |
| Verbrauch Jahr | m³ / L | Summe des laufenden Jahres |
| Aktueller Wasserdurchfluss | L/h | Momentaner Durchfluss |
| Ø Wasserverbrauch täglich | L/d | Durchschnitt pro Tag |
| Natürliche Wasserhärte | °dH | Eingestellte Rohwasserhärte |
| Dosiermenge / -Einstellung | — | Aktuelle Dosierung + Modus (z. B. „normal") |
| **Minerallösung Vorrat** | % | Füllstand (aus Rest/Kapazität berechnet) |
| Minerallösung Rest / Behältergröße | mL | Verbleibende Menge / Kapazität (RFID-Tank) |
| Minerallösung Reichweite / Typ | — | Restreichweite / Kartuschen-Sorte |
| **Gerätestatus** | — | Fehler/Warnung im Klartext (Diagnose) |
| Minerallösung Haltbarkeit / Mengenstatus | — | MHD- & Mengen-Warnung (Diagnose) |
| Verbindung Steuerelektronik | — | Modul ↔ Geräte-Elektronik (Diagnose) |
| Gerätealter | Jahre | Berechnet aus der Inbetriebnahme (Diagnose) |
| Inbetriebnahme / Service-Datum | Datum | Wartungstermine (Diagnose) |
| Modul-Firmware / Seriennummer | — | Diagnose |

## Steuerung

| Entität | Typ | Funktion |
|---|---|---|
| **Dosiermenge** | Select | Konzentration umschalten: `minimal` / `normal` / `maximal` |

Die Select-Entität schreibt `concentration adjustment` ans Gerät. Der
Diagnose-Sensor *„Dosiermenge-Einstellung"* zeigt den zurückgelesenen Wert —
so lässt sich kontrollieren, ob das Umschalten am Gerät angekommen ist.

> ⚠️ Dies ändert die **reale Trinkwasser-Dosierung** des i-dos.

## Warnung

| Entität | Typ | Auslöser |
|---|---|---|
| **Minerallösung Warnung** | binary_sensor (problem) | Vorrat < 10 %, Gerätestatus ≠ OK oder MHD-/Mengen-Warnung |

Eine fertige Benachrichtigungs-Automation liegt unter
[`examples/automation_mineral_warning.yaml`](examples/automation_mineral_warning.yaml).

---

## Installation

### Über HACS (empfohlen)

1. HACS → **Integrationen** → ⋮ → **Benutzerdefinierte Repositories**
2. URL `https://github.com/x1marc/homeassistant-judo-idos` hinzufügen,
   Kategorie **Integration**
3. **JUDO i-dos** installieren
4. Home Assistant neu starten

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=x1marc&repository=homeassistant-judo-idos&category=integration)

### Manuell

1. Ordner `custom_components/myjudo` nach `config/custom_components/` kopieren
2. Home Assistant neu starten

---

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „JUDO i-dos"**

| Feld | Beispiel | Hinweis |
|---|---|---|
| Benutzername | `dein-login` | dein myjudo.eu-Login |
| Passwort | `••••••••` | Klartext (kein MD5) |
| Seriennummer | `NNNNN` | steht am Gerät / in der App |
| Abrufintervall | `15` | Minuten (5–60) |

Das Abrufintervall lässt sich später über **Konfigurieren** auf der
Integrations-Karte ändern.

---

## Beispiele

Im Ordner [`examples/`](examples/) liegt eine fertige Automation, die dich
**einmal jährlich an die Wartung** erinnert (persistente Notiz).

---

## Funktionsweise

```
Login    →  GET /?group=register&command=login&user=…&password=…&role=customer
Connect  →  GET /?token=…&group=register&command=connect&parameter=i-dos&serial number=…
Daten    →  GET /?token=…&group=consumption&command=water total   (sequenziell)
```

- **Server:** `https://www.my-judo.com:8124/` (OptiSoft-Relay)
- Jeder Abruf macht einen frischen Login (Token läuft schnell ab)
- Datenabrufe laufen **sequenziell** — der Geräte-Relay verarbeitet nur eine
  Anfrage gleichzeitig

### Technische Besonderheiten

Der JUDO-Server ist alt (TLS 1.2, selbstsigniertes Zertifikat). HA Core nutzt
OpenSSL 3.x (strenger). Die Integration baut die HTTPS-Verbindung daher mit
Pythons `ssl`/`http.client` selbst auf:

| Problem | Ursache | Lösung |
|---|---|---|
| `SSLEOFError` beim Handshake | OpenSSL 3.x bietet TLS 1.3 an, Server bricht ab | TLS auf 1.2 pinnen |
| Zertifikat abgelehnt | `SECLEVEL=2` zu streng für altes Cert | `SECLEVEL=1` + `CERT_NONE` |
| `Can't use SSL_get_servername` | rohe IP als SNI gesendet | Hostname als SNI, IP nur fürs TCP |
| Alle Abrufe `TimeoutError` | parallele Anfragen | sequenziell + kleine Pause |

---

## Fehlersuche

Debug-Logging (`configuration.yaml`):

```yaml
logger:
  default: warning
  logs:
    custom_components.myjudo: debug
```

Live mitlesen: `ha core logs -f | grep JUDO`

| Meldung | Bedeutung |
|---|---|
| `Login failed: …` | Benutzername/Passwort falsch |
| `Connect failed: …` | Seriennummer falsch oder Gerät offline |
| `STEP 1 TCP FAILED` | Port 8124 blockiert (Firewall) |
| `STEP 2 SSL FAILED` | TLS-Problem |
| `HTTP failed … TimeoutError` | Gerät war offline / Relay überlastet |

> Ist das Gerät in der myjudo.eu-App **offline**, liefert auch die Integration
> keine Daten — zuerst die WLAN-Verbindung des i-dos prüfen.

---

## Kompatibilität

Getestet mit der Geräteklasse **i-dos**. Andere JUDO-Geräte (i-soft, ZEWA)
nutzen teils andere Kommandos und sind nicht getestet — Feedback / PRs
willkommen.

## Haftungsausschluss

Inoffizielle Integration, **nicht** von JUDO unterstützt oder geprüft.
Nutzung auf eigene Verantwortung. „JUDO" und „i-dos" sind Marken der
jeweiligen Inhaber.

## Mitwirken

Issues und Pull Requests sind willkommen! Bitte bei Fehlern die
JUDO-Log-Zeilen (`grep JUDO`) mit anhängen.

## Changelog

- **1.11.1** – `configuration_url` → klickbarer Link zum myjudo.eu-Portal auf
  der Geräteseite
- **1.11.0** – Keep-Alive (1 TLS-Verbindung pro Poll statt ~23 → weniger
  Handshakes/DNS, kein Log-Spam, mit Reconnect); neuer Sensor „Letzter Abruf";
  deutlich detaillierteres Debug-Log (pro Befehl Wert + Einheit + Dauer)
- **1.10.4** – Sensor „Letzter Abruf" + Logbuch-Custom-Call entfernt
- **1.10.3** – (durch 1.10.4 ersetzt)
- **1.10.2** – Fix: RestoreSensor war wirkungslos (geerbte `available` zeigte
  Sensoren nach Reload trotz Wert als unavailable) → jetzt wirklich keine
  Lücke; binary_sensor restore-fähig; Dosier-Umschalten wirft
  `HomeAssistantError` statt `UpdateFailed`
- **1.10.1** – Fix: unvollständiger Static-Cache beim ersten Abruf nach Neustart
- **1.10.0** – Minerallösung-Warnung (binary_sensor) + Beispiel-Automation;
  statische Werte werden nur noch 1×/Tag abgerufen (schnellere Polls)
- **1.9.6** – Fix: Options-Dialog ließ sich nicht öffnen (500-Fehler) — OptionsFlow
  wurde noch mit Argument erzeugt
- **1.9.5** – Sensoren behalten ihren Wert über Reload/Neustart (`RestoreSensor`);
  Standard-Abrufintervall auf 30 Min
- **1.9.4** – Fix: Abrufintervall im Options-Dialog wird korrekt gespeichert/
  angezeigt; veralteten OptionsFlow-`__init__` entfernt
- **1.9.3** – Anti-Flapping auch bei partiellen Timeouts (Kernwert-Prüfung);
  toten „Salzmenge"-Sensor entfernt
- **1.9.2** – Anti-Flapping: kurzer Server-Timeout setzt Sensoren nicht mehr
  auf „unavailable" (kein Logbuch-Spam); ein Logbuch-Eintrag pro erfolgreichem
  Abruf
- **1.9.1** – Logbuch-Eintrag pro Abruf entfernt (zu viele Einträge)
- **1.9.0** – Ausfall-Benachrichtigung (persistente Notiz nach 3 Fehlern,
  Auflösung bei Erholung)
- **1.8.2** – Fix Brand-Validierung (doppeltes logo.png entfernt)
- **1.8.1** – Eigenes Brand-Logo im `brand/`-Ordner (HA 2026.3+); HACS
  brands-Check wieder aktiv
- **1.8.0** – Dosiermengen-Steuerung per Select-Entität (minimal/normal/
  maximal); CI-Fixes (manifest-Sortierung, HACS brands-Check)
- **1.7.1** – Status-Sensoren in die Diagnose-Kategorie verschoben
- **1.7.0** – Minerallösung Reichweite/Typ/MHD/Mengenstatus, Verbindungsstatus
  Steuerelektronik (entdeckt via ParameterController)
- **1.6.0** – Minerallösungs-Sensoren (Vorrat %, Rest & Behältergröße in mL),
  Dosiermenge-Einstellung, Gerätestatus als Klartext
- **1.5.0** – Robustheit: getrennte Connect-/Read-Timeouts, klarere Fehler
- **1.4.0** – Diagnose-Sensoren: Gerätealter, Inbetriebnahme, Service, Modul-FW
- **1.3.0** – Liter-Sensoren zusätzlich zu m³
- **1.2.0** – Verbrauch heute/Woche/Monat/Jahr
- **1.1.0** – DNS mit IP-Fallback, Phasen-Logging
- **1.0.0** – Erste Version

## Lizenz

[MIT](LICENSE)
