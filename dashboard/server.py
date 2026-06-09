import http.server
import socketserver
import os
import sys

PORT = 5174

# Cambiamos al directorio raíz del proyecto (un nivel arriba de dashboard)
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class NoCacheHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

with socketserver.TCPServer(("", PORT), NoCacheHTTPRequestHandler) as httpd:
    print(f"===========================================================")
    print(f"[*] Dashboard Server running at: http://localhost:{PORT}/dashboard/")
    print(f"[*] Serving directory: {os.getcwd()}")
    print(f"===========================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo el servidor...")
        httpd.server_close()
        sys.exit(0)
