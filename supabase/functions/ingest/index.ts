// Infraestrutura adaptada para o projeto de umidade do solo.
// Supabase Edge Runtime, Deno. Sem dependências externas.
const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});

export async function handler(req: Request): Promise<Response> {
  if (req.method !== "POST") return reply({error: "method_not_allowed"}, 405);
  
  const secret = Deno.env.get("INGEST_KEY");
  const base = Deno.env.get("SUPABASE_URL");
  
  // As chaves nomeadas são provisionadas pelo Supabase. Preferir a chave nova.
  let admin: string | undefined;
  try { admin = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}").default; }
  catch { return reply({error: "invalid_server_keys"}, 500); }
  admin ||= Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  
  if (admin && typeof admin !== "string") return reply({error: "invalid_server_keys"}, 500);
  if (!secret || secret.length < 32 || !base || !admin)
    return reply({error: "server_not_configured"}, 500);
    
  if (req.headers.get("x-ingest-key") !== secret)
    return reply({error: "unauthorized"}, 401);
    
  if (!(req.headers.get("content-type") || "").toLowerCase().startsWith("application/json"))
    return reply({error: "json_required"}, 400);
    
  const text = await req.text();
  if (text.length > 4096) return reply({error: "payload_too_large"}, 413);
  
  let body: any;
  try { body = JSON.parse(text); } catch { return reply({error: "invalid_json"}, 400); }
  
  const r = body?.reading;
  if (!r || typeof r !== "object" || Array.isArray(r)) return reply({error: "invalid_reading"}, 400);
  
  // Validações alinhadas com as constraints da tabela public.readings
  const validId = typeof r.device_id === "string" && /^[a-z0-9_-]{1,40}$/.test(r.device_id);
  const validMessage = typeof r.message_id === "string" && r.message_id.trim().length > 0 && r.message_id.length <= 120;
  const validH = typeof r.humidity === "number" && Number.isFinite(r.humidity) && r.humidity >= 0 && r.humidity <= 100;
  const validEmergency = typeof r.emergency_activated === "boolean";
  const validSoil = r.soil_condition === "seca" || r.soil_condition === "humida";

  if (!validId || !validMessage || !validH || !validEmergency || !validSoil || body.topic !== `turma/${r.device_id}/telemetria`)
    return reply({error: "invalid_contract"}, 400);
    
  // received_at é definido pelo DEFAULT do banco. Ignorar campos extras do cliente.
  const row = {
    device_id: r.device_id,
    message_id: r.message_id,
    humidity: r.humidity,
    emergency_activated: r.emergency_activated,
    soil_condition: r.soil_condition
  };

  try {
    const res = await fetch(base + "/rest/v1/readings?on_conflict=device_id,message_id", {
      method: "POST", 
      headers: {
        "Content-Type": "application/json", 
        apikey: admin,
        // Chave sb_secret usa apikey; JWT legado também precisa do Bearer.
        ...(admin.startsWith("sb_secret_") ? {} : {Authorization: "Bearer " + admin}),
        Prefer: "resolution=ignore-duplicates,return=representation"
      }, 
      body: JSON.stringify(row), 
      signal: AbortSignal.timeout(10000)
    });
    
    if (!res.ok) {
      console.error("database_status", res.status, "message_id", r.message_id);
      return reply({error: "database_error", message_id: r.message_id}, 500);
    }
    
    const inserted = await res.json();
    return reply({ok: true, inserted: inserted.length > 0, message_id: r.message_id}, inserted.length ? 201 : 200);
  } catch (e) {
    console.error("ingest_failure", e instanceof Error ? e.name : "error");
    return reply({error: "ingest_failure"}, 500);
  }
}

Deno.serve(handler);
