# Monitor de umidade do solo

Projeto de irrigação com ESP32 simulado no Wokwi. O dispositivo lê a umidade do solo, liga a bomba quando a terra está seca e manda as leituras para uma API no Supabase. O painel mostra o histórico das leituras recebidas.

- Simulação no Wokwi: https://wokwi.com/projects/480981275261329409
- Painel publicado: https://umidade.pages.dev/

## Como funciona

```
ESP32 (Wokwi) --HTTPS POST--> Edge Function "ingest" (Supabase) --> tabela no Postgres
                                                                         |
Painel (Cloudflare Pages) <------------- consulta a cada 10 s -----------+
```

O ESP32 lê o sensor a cada 200 ms e envia uma leitura a cada 3 s. Quando o botão de emergência muda de estado, ele envia na hora. Cada envio é um JSON assim:

```json
{
  "topic": "turma/esp32_planta_01/telemetria",
  "reading": {
    "device_id": "esp32_planta_01",
    "message_id": "esp32_planta_01-a1b2c3d4-12",
    "humidity": 35,
    "emergency_activated": false,
    "soil_condition": "seca"
  }
}
```

O `message_id` junta o id do dispositivo, um id aleatório gerado a cada boot e um contador. Assim dá para saber se alguma mensagem se perdeu ou chegou repetida.

Regras do dispositivo:
- umidade abaixo de 40% é considerada solo seco: acende o LED "terra seca" e liga a bomba;
- o botão de emergência desliga a bomba, mas os LEDs continuam mostrando o estado do solo;
- o LCD mostra a umidade e uma barra, ou "EMERGENCIA ATIVA";
- digitar `x` + Enter no monitor serial pausa ou retoma a rede (a leitura local continua).

## Estrutura

```
dispositivo/   código MicroPython do ESP32 e diagrama do Wokwi
```

## Como reproduzir

### Dispositivo (Wokwi)

1. Crie um projeto ESP32 MicroPython no Wokwi.
2. Copie `dispositivo/main.py` e `dispositivo/diagram.json`.
3. Crie um `config.py` a partir de `dispositivo/config.exemplo.py`, com a URL da sua Edge Function e a chave de ingestão.
4. Rode a simulação e mexa no potenciômetro do sensor de umidade. O monitor serial mostra `ENVIADO SUPABASE [HTTP 200]` a cada envio.

## Limitações

- O Wokwi usa a rede `Wokwi-GUEST`, então a simulação precisa estar rodando no navegador para os dados chegarem.
- A chave de ingestão fica no dispositivo. Num projeto público do Wokwi, qualquer pessoa consegue vê-la, então ela deve ser trocada depois da apresentação.
- O painel mostra a hora do último registro recebido, mas isso não garante que o dispositivo continua conectado.
