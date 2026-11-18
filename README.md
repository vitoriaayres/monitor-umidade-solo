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
dispositivo/                 código MicroPython do ESP32 e diagrama do Wokwi
supabase/functions/ingest/   API que recebe as leituras (Edge Function, Deno)
banco/schema.sql             tabela readings, índice e permissões
painel/                      página que mostra o histórico
```

## API

`POST /functions/v1/ingest` com o header `x-ingest-key`. A função confere a chave e valida o JSON (os mesmos limites da tabela). Depois grava a leitura usando a chave secreta do Supabase. Quem define a hora de recebimento é o banco (`received_at`), não o dispositivo.

| Resposta | Quando |
|---|---|
| 201 | leitura nova gravada |
| 200 | `message_id` repetido, ignorado |
| 400 | JSON inválido ou fora do contrato |
| 401 | chave errada ou ausente |
| 413 | corpo maior que 4 KB |

## Banco

Tabela `public.readings`, com chave primária `(device_id, message_id)`, para a mesma mensagem não entrar duas vezes. O RLS está ligado e só permite leitura pública (`select`). Por isso o painel consegue consultar com a chave publishable, mas não consegue inserir nada.

## Como reproduzir

### 1. Banco

No Supabase, abra o SQL Editor e rode `banco/schema.sql`.

### 2. API

Com a [CLI do Supabase](https://supabase.com/docs/guides/cli):

```
supabase login
supabase link --project-ref SEU-PROJETO
supabase secrets set INGEST_KEY=uma-chave-com-pelo-menos-32-caracteres
supabase functions deploy ingest --no-verify-jwt
```

O `--no-verify-jwt` é necessário porque o ESP32 se autentica pelo `x-ingest-key`, não por login.

Teste rápido:

```
curl -X POST https://SEU-PROJETO.supabase.co/functions/v1/ingest \
  -H "Content-Type: application/json" -H "x-ingest-key: SUA-CHAVE" \
  -d '{"topic":"turma/teste_01/telemetria","reading":{"device_id":"teste_01","message_id":"teste-1","humidity":50,"emergency_activated":false,"soil_condition":"humida"}}'
```

### 3. Dispositivo (Wokwi)

1. Crie um projeto ESP32 MicroPython no Wokwi.
2. Copie `dispositivo/main.py` e `dispositivo/diagram.json`.
3. Crie um `config.py` a partir de `dispositivo/config.exemplo.py`, com a URL da sua Edge Function e a chave de ingestão.
4. Rode a simulação e mexa no potenciômetro do sensor de umidade. O monitor serial mostra `ENVIADO SUPABASE [HTTP 201]` a cada envio.

### 4. Painel

1. Copie `painel/config.exemplo.js` para `painel/config.js` e coloque a URL do projeto e a chave **publishable** (Project Settings > API Keys). Nunca a secret.
2. Para testar localmente: `python -m http.server` dentro de `painel/` e abra http://localhost:8000.
3. Para publicar, suba a pasta `painel/` no Cloudflare Pages (Workers & Pages > Create > Pages > Upload assets).

## Limitações

- O Wokwi usa a rede `Wokwi-GUEST`, então a simulação precisa estar rodando no navegador para os dados chegarem.
- A chave de ingestão fica no dispositivo. Num projeto público do Wokwi, qualquer pessoa consegue vê-la, então ela deve ser trocada depois da apresentação.
- O painel mostra a hora do último registro recebido, mas isso não garante que o dispositivo continua conectado.
