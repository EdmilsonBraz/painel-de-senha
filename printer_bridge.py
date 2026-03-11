import time
import json
import serial
from http.server import BaseHTTPRequestHandler, HTTPServer
from escpos.printer import Serial as SerialPrinter

# CONFIGURAÇÃO PADRÃO (Pode ser alterada via Totem no navegador)
DEFAULT_PORT = "COM5" 
DEFAULT_BAUD = 9600

class PrinterBridgeHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/print':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            port = data.get('port', DEFAULT_PORT)
            baud = data.get('baud', DEFAULT_BAUD)
            content = data.get('content', '')
            
            # Limpeza do nome da porta (ex: "Bematech_COM5" ou "COM5:" vira "COM5")
            port = port.split(':')[-1].strip() # Remove "Bematech_" se for o caso
            if "_" in port: port = port.split("_")[-1]
            
            print(f"Tentando imprimir em: {port}...")
            
            try:
                # Usa PySerial bruto direto, sem a biblioteca python-escpos, para evitar lixo ("vb", "!") gerado por cabeçalhos ocultos.
                try:
                    p = serial.Serial(port, baudrate=baud, timeout=2)
                except:
                    p = serial.Serial(f"\\\\.\\{port}", baudrate=baud, timeout=2)
                
                if 'password' in data:
                    t_name = data.get('tenant_name', '')
                    t_sub = data.get('system_subtitle', '')
                    pw = data.get('password', '')
                    t_type = data.get('type_name', '')
                    date_str = data.get('date', '')
                    time_str = data.get('time', '')
                    
                    def cmd(c): p.write(c)
                    
                    # A Bematech aceita muito bem cp850 (DOS) em modo serial puro.
                    def print_text(text):
                        p.write(text.encode('cp850', errors='replace'))
                    
                    cmd(b'\x1b\x40')     # Inicializa impressora (limpa buffer)
                    cmd(b'\x1b\x61\x01') # Alinhamento central
                    
                    cmd(b'\x1b\x45\x01') # Negrito ON
                    print_text(t_name.upper() + "\n")
                    
                    if t_sub:
                        cmd(b'\x1b\x45\x00') # Negrito OFF
                        print_text(t_sub + "\n")
                        
                    print_text("--------------------------------\n\n")
                    
                    cmd(b'\x1b\x45\x01') # Negrito ON
                    print_text("SENHA DE ATENDIMENTO\n\n")
                    
                    # Aumenta senha para o gigante usando comandos NATIVOS Bematech
                    cmd(b'\x1b\x57\x01') # Expande largura
                    cmd(b'\x1b\x64\x01') # Expande altura
                    print_text(pw + "\n\n")
                    
                    cmd(b'\x1b\x57\x00') # Retorna largura normal
                    cmd(b'\x1b\x64\x00') # Retorna altura normal
                    cmd(b'\x1b\x45\x00') # Negrito OFF
                    
                    print_text(t_type + "\n\n")
                    print_text("--------------------------------\n")
                    print_text(f"Retirada: {date_str} as {time_str}\n")
                    print_text("Aguarde ser chamado no painel\n")
                    
                    cmd(b'\n\n\n\n\n')
                    cmd(b'\x1b\x6d') # Comando de corte clássico M-Cutter
                else:
                    content = data.get('content', '')
                    p.write(content.encode('cp850', errors='replace'))
                    p.write(b'\n\n\n\n\n')
                    p.write(b'\x1b\x6d')
                
                p.close()
                self._send_response(200, {"status": "success"})
                print("Impressão enviada com sucesso!")
            except Exception as e:
                print(f"Erro ao imprimir: {e}")
                self._send_response(500, {"status": "error", "message": str(e)})

    def _send_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.write(json.dumps(data).encode('utf-8'))

    def write(self, data):
        self.wfile.write(data)

def run_bridge(port=8001):
    server_address = ('', port)
    httpd = HTTPServer(server_address, PrinterBridgeHandler)
    print(f"--- BRIDGE BEMATECH ATIVA NA PORTA {port} ---")
    print(f"Configurada para porta serial: {DEFAULT_PORT}")
    print("Mantenha esta janela aberta para imprimir.")
    httpd.serve_forever()

if __name__ == "__main__":
    run_bridge()
