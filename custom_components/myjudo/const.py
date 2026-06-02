DOMAIN = "myjudo"

# JUDO OptiSoft relay server (API_OPTISOFT in the myjudo.eu portal config).
# DNS is tried first; API_IP is only a fallback if resolution fails.
API_HOST = "www.my-judo.com"
API_IP   = "178.15.150.126"   # fallback only — update here if JUDO moves the server
API_PORT = 8124

# Split timeouts: TCP+SSL should connect fast; the read waits for the device
# relay to answer. Keeping the read timeout moderate means a JUDO server outage
# (connection ok, but no HTTP response) fails fast instead of hanging 30 s.
API_CONNECT_TIMEOUT = 10   # seconds for TCP + SSL handshake
API_TIMEOUT = 20           # seconds to wait for the HTTP response (read)

CONF_SERIAL = "serial_number"

DEFAULT_SCAN_INTERVAL = 30  # minutes
