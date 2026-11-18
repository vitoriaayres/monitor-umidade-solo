-- Tabela que guarda as leituras enviadas pelo ESP32.
-- Rodar no SQL Editor do Supabase.

create table public.readings (
  device_id           text not null check (device_id ~ '^[a-z0-9_-]{1,40}$'),
  message_id          text not null check (length(trim(message_id)) >= 1 and length(trim(message_id)) <= 120),
  humidity            double precision not null check (humidity >= 0 and humidity <= 100),
  emergency_activated boolean not null default false,
  soil_condition      text not null check (soil_condition in ('seca', 'humida')),
  received_at         timestamptz not null default now(),
  -- a mesma mensagem não entra duas vezes
  primary key (device_id, message_id)
);

-- o painel busca as últimas leituras de um dispositivo
create index readings_device_time on public.readings (device_id, received_at desc);

-- leitura pública para o painel; só a Edge Function (chave secreta) consegue inserir
alter table public.readings enable row level security;

create policy synthetic_lab_public_read on public.readings
  for select to anon, authenticated
  using (true);
