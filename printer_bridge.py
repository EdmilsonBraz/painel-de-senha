import time
import json
import serial
from http.server import BaseHTTPRequestHandler, HTTPServer

# CONFIGURAÇÃO PADRÃO
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
            
            # Limpeza do nome da porta
            port = port.split(':')[-1].strip()
            if "_" in port: port = port.split("_")[-1]
            
            print(f"[{time.strftime('%H:%M:%S')}] Imprimindo senha {data.get('password')} em {port}...")
            
            try:
                try:
                    p = serial.Serial(port, baudrate=baud, timeout=2)
                except:
                    p = serial.Serial(f"\\\\.\\{port}", baudrate=baud, timeout=2)
                
                if 'password' in data:
                    t_name = data.get('tenant_name', '')
                    t_sub  = data.get('system_subtitle', '')
                    pw     = data.get('password', '')
                    t_type = data.get('type_name', '')
                    date_str = data.get('date', '')
                    time_str = data.get('time', '')
                    
                    def cmd(c): p.write(c)
                    def print_text(text):
                        p.write(text.encode('cp850', errors='replace'))
                    
                    cmd(b'\x1b\x40')     # Inicializa
                    cmd(b'\x1b\x61\x01') # Centraliza
                    
                    # Nome da Unidade
                    cmd(b'\x1b\x45\x01') # Negrito ON
                    print_text(t_name.upper() + "\n")
                    
                    # Subtítulo (Seja bem-vindo)
                    if t_sub:
                        cmd(b'\x1b\x45\x00') # Negrito OFF
                        print_text(t_sub + "\n")
                        
                    print_text("--------------------------------\n\n")
                    
                    # Senha
                    cmd(b'\x1b\x45\x01') # Negrito ON
                    print_text("SENHA DE ATENDIMENTO\n\n")
                    
                    cmd(b'\x1b\x57\x01') # Expande largura
                    cmd(b'\x1b\x64\x01') # Expande altura
                    print_text(pw + "\n\n")
                    
                    cmd(b'\x1b\x57\x00') # Normal
                    cmd(b'\x1b\x64\x00') 
                    cmd(b'\x1b\x45\x00') # Negrito OFF
                    
                    # Tipo/Serviço
                    print_text(t_type + "\n\n")
                    
                    print_text("--------------------------------\n")
                    print_text(f"Retirada: {date_str} as {time_str}\n")
                    print_text("Aguarde ser chamado no painel\n")
                    
                    cmd(b'\n\n\n\n\n')
                    cmd(b'\x1b\x6d') # Corte
                
                p.close()
                self._send_response(200, {"status": "success"})
            except Exception as e:
                print(f"Erro ao imprimir: {e}")
                self._send_response(500, {"status": "error", "message": str(e)})

    def _send_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

def run_bridge(port=8001):
    server_address = ('', port)
    httpd = HTTPServer(server_address, PrinterBridgeHandler)
    print(f"--- BRIDGE BEMATECH ATIVA NA PORTA {port} ---")
    print("Modo de compatibilidade clássica (HTTP Bridge)")
    httpd.serve_forever()

if __name__ == "__main__":
    run_bridge()
