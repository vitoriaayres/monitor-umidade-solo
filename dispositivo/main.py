import sys
import time
import json
import select
import network
import _thread
import ubinascii
import os
from machine import Pin, I2C, ADC

try:
    import urequests as requests
except ImportError:
    import requests

# ==========================================
# CONFIGURAÇÕES (ficam no config.py, fora do git)
# ==========================================
from config import WIFI_SSID, WIFI_PASS, EDGE_URL, INGEST_KEY, DEVICE_ID, SEND_INTERVAL_MS

# ==========================================
# PINOS
# ==========================================
PIN_SENSOR = 34
PIN_BOMBA = 23
PIN_BOTAO = 4
PIN_LED_SECO = 18
PIN_LED_OK = 19

INTERVALO_LCD = 500
INTERVALO_SENSOR = 200

# ==========================================
# ESTADO COMPARTILHADO (protegido por lock)
# ==========================================
lock = _thread.allocate_lock()
estado = {
    "umidade": 0,
    "pausada": False,
    "contador": 0,
}
emergencia = False  # alterada pela interrupção
boot_id = ubinascii.hexlify(os.urandom(4)).decode()


# ==========================================
# DRIVER LCD I2C (PCF8574 + HD44780) 16x2
# ==========================================
class LCD:
    def __init__(self, i2c, addr=0x27):
        self.i2c = i2c
        self.addr = addr
        self.bl = 0x08
        time.sleep_ms(50)
        for _ in range(3):
            self._send4(0x30, 0)
            time.sleep_ms(5)
        self._send4(0x20, 0)
        self._send(0x28, 0)  # 4 bits, 2 linhas
        self._send(0x0C, 0)  # display on, sem cursor
        self._send(0x06, 0)  # incremento
        self.clear()

    def _write(self, b):
        self.i2c.writeto(self.addr, bytes([b | self.bl]))

    def _pulse(self, b):
        self._write(b | 0x04)
        time.sleep_us(2)
        self._write(b & ~0x04)
        time.sleep_us(60)

    def _send4(self, nib, rs):
        self._pulse((nib & 0xF0) | rs)

    def _send(self, val, rs):
        self._send4(val & 0xF0, rs)
        self._send4((val << 4) & 0xF0, rs)

    def clear(self):
        self._send(0x01, 0)
        time.sleep_ms(2)

    def set_cursor(self, col, row):
        self._send(0x80 | (col + (0x40 if row else 0)), 0)

    def print(self, texto):
        for ch in str(texto):
            self._send(ord(ch), 1)

    def write(self, codigo):
        self._send(codigo, 1)


# ==========================================
# INTERRUPÇÃO DO BOTÃO (com debounce)
# ==========================================
ultimo_clique = 0


def tratar_interrupcao(pin):
    global emergencia, ultimo_clique
    agora = time.ticks_ms()
    if time.ticks_diff(agora, ultimo_clique) > 250:
        emergencia = not emergencia
        ultimo_clique = agora


# ==========================================
# TAREFA DE REDE (thread separada)
# ==========================================
def tarefa_rede():
    wlan = network.WLAN(network.STA_IF)
    ultimo_envio = None
    ultimo_emerg = emergencia
    pausa_confirmada = False

    while True:
        with lock:
            pausado = estado["pausada"]

        # 1. Pausa via Serial ('x')
        if pausado:
            if wlan.active():
                wlan.disconnect()
                wlan.active(False)
            if not pausa_confirmada:
                print("REDE PAUSADA: aquisicao local continua")
                pausa_confirmada = True
            time.sleep_ms(100)
            continue
        pausa_confirmada = False

        # 2. Garante conexão Wi-Fi
        if not wlan.isconnected():
            wlan.active(True)
            wlan.connect(WIFI_SSID, WIFI_PASS)
            inicio = time.ticks_ms()
            while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), inicio) < 15000:
                time.sleep_ms(100)
            if wlan.isconnected():
                print("WIFI CONECTADO | IP:", wlan.ifconfig()[0])
                ultimo_envio = None
            else:
                print("FALHA REDE: Tempo de Wi-Fi excedido")
                time.sleep_ms(2000)
                continue

        # 3. Envio periódico
        agora = time.ticks_ms()
        mudou_emerg = emergencia != ultimo_emerg
        if (ultimo_envio is None or mudou_emerg
                or time.ticks_diff(agora, ultimo_envio) >= SEND_INTERVAL_MS):
            with lock:
                umid = estado["umidade"]
                estado["contador"] += 1
                num_msg = estado["contador"]
            emerg = emergencia
            ultimo_emerg = emerg

            solo = "seca" if umid < 40 else "humida"
            msg_id = "{}-{}-{}".format(DEVICE_ID, boot_id, num_msg)

            payload = json.dumps({
                "topic": "turma/{}/telemetria".format(DEVICE_ID),
                "reading": {
                    "device_id": DEVICE_ID,
                    "message_id": msg_id,
                    "humidity": umid,
                    "emergency_activated": emerg,
                    "soil_condition": solo,
                },
            })
            headers = {
                "Content-Type": "application/json",
                "x-ingest-key": INGEST_KEY,
            }

            try:
                r = requests.post(EDGE_URL, data=payload, headers=headers)
                print("ENVIADO SUPABASE [HTTP {}]: {}".format(r.status_code, msg_id))
                r.close()
            except Exception as e:
                print("FALHA HTTP:", e)
            ultimo_envio = time.ticks_ms()

        time.sleep_ms(50)


# ==========================================
# CONFIGURAÇÃO INICIAL
# ==========================================
sensor = ADC(Pin(PIN_SENSOR))
sensor.atten(ADC.ATTN_11DB)  # faixa completa 0-3.3V

bomba = Pin(PIN_BOMBA, Pin.OUT)
led_seco = Pin(PIN_LED_SECO, Pin.OUT)
led_ok = Pin(PIN_LED_OK, Pin.OUT)
botao = Pin(PIN_BOTAO, Pin.IN, Pin.PULL_UP)
botao.irq(trigger=Pin.IRQ_FALLING, handler=tratar_interrupcao)

i2c = I2C(0, sda=Pin(21), scl=Pin(22), freq=400000)
lcd = LCD(i2c, 0x27)
lcd.set_cursor(0, 0)
lcd.print("SISTEMA ATIVO")
time.sleep(1)
lcd.clear()

print("Irrigacao + Supabase HTTP | Sensor GPIO34 | Botao GPIO4")
print("Envie x + Enter no Serial para pausar/retomar a rede")

# Entrada serial não bloqueante
poll = select.poll()
poll.register(sys.stdin, select.POLLIN)

# TLS precisa de bastante pilha na thread
_thread.stack_size(16384)
_thread.start_new_thread(tarefa_rede, ())

# ==========================================
# LOOP PRINCIPAL - CONTROLE LOCAL
# ==========================================
t_sensor = time.ticks_ms()
t_lcd = time.ticks_ms()

while True:
    # Comando 'x' no monitor serial
    while poll.poll(0):
        tecla = sys.stdin.read(1)
        if tecla in ("x", "X"):
            with lock:
                estado["pausada"] = not estado["pausada"]
                pedido = estado["pausada"]
            print("PEDIDO: PAUSA" if pedido else "PEDIDO: RETOMADA")

    agora = time.ticks_ms()

    # TAREFA 1: leitura do sensor
    if time.ticks_diff(agora, t_sensor) >= INTERVALO_SENSOR:
        t_sensor = agora
        valor = sensor.read_u16() >> 4  # 0..4095
        nova_umidade = (4095 - valor) * 100 // 4095

        with lock:
            estado["umidade"] = nova_umidade
        emerg = emergencia

        seco = nova_umidade < 40
        # Emergência desliga só a bomba; os LEDs continuam mostrando o solo
        bomba.value(1 if (seco and not emerg) else 0)
        led_seco.value(1 if seco else 0)
        led_ok.value(0 if seco else 1)

    # TAREFA 2: LCD
    if time.ticks_diff(agora, t_lcd) >= INTERVALO_LCD:
        t_lcd = agora
        with lock:
            umid_display = estado["umidade"]
        emerg_display = emergencia

        lcd.set_cursor(0, 0)
        lcd.print("Umid: {}%   ".format(umid_display))

        lcd.set_cursor(0, 1)
        if emerg_display:
            lcd.print("EMERGENCIA ATIVA")
        else:
            blocos = umid_display // 10
            for i in range(10):
                if i < blocos:
                    lcd.write(255)
                else:
                    lcd.print(" ")
            lcd.print("      ")

    time.sleep_ms(10)