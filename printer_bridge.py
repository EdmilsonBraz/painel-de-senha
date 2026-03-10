import serial
import time
import requests
from escpos.printer import Serial as SerialPrinter

# CONFIGURAÇÕES
SERIAL_PORT = "COM3"  # Ajuste para a porta onde a impressora está ligada
BAUD_RATE = 9600
API_URL = "http://localhost:9000"

# Mapeamento do que a impressora envia para os botões
# Muitos totens enviam '1', '2', '3', '4' ou 'A', 'B', 'C', 'D'
BUTTON_MAP = {
    "1": "N",
    "2": "P",
    "3": "E",
    "4": "O",
    "A": "N",
    "B": "P",
    "C": "E",
    "D": "O"
}

def print_ticket(password):
    try:
        # Tenta abrir a impressora apenas para imprimir e fecha
        # No Windows, a porta serial pode ser compartilhada se soubermos gerenciar,
        # senão precisamos de um lock.
        p = SerialPrinter(SERIAL_PORT, baudrate=BAUD_RATE)
        p.set(align='center', font='a', width=2, height=2)
        p.text("\n\n")
        p.text("VBN ATENDIMENTO\n")
        p.set(align='center', font='a', width=4, height=4)
        p.text(f"\n{password}\n\n")
        p.set(align='center', font='a', width=1, height=1)
        p.text(time.strftime("%d/%m/%Y %H:%M:%S") + "\n")
        p.text("\n------------------------------\n")
        p.cut()
        p.close()
    except Exception as e:
        print(f"ERRO AO IMPRIMIR: {e}")

def monitor_buttons():
    print(f"Iniciando monitoramento na porta {SERIAL_PORT}...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        while True:
            if ser.in_waiting > 0:
                char = ser.read().decode('utf-8', errors='ignore').strip()
                if char in BUTTON_MAP:
                    type = BUTTON_MAP[char]
                    print(f"Botão {char} pressionado. Gerando senha {type}...")
                    
                    # Chama a API para gerar a senha
                    try:
                        res = requests.post(f"{API_URL}/api/generate/{type}")
                        data = res.json()
                        if "password" in data:
                            print(f"Senha gerada: {data['password']}. Imprimindo...")
                            print_ticket(data['password'])
                    except Exception as e:
                        print(f"Erro na API: {e}")
            time.sleep(0.01)
    except Exception as e:
        print(f"Erro ao abrir porta serial: {e}")
        print("DICA: Verifique se a porta COM correta está configurada no arquivo.")

if __name__ == "__main__":
    monitor_buttons()
