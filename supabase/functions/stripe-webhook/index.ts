// Supabase Edge Function: Stripe webhook -> activate member plan
// Deploy:  supabase functions deploy stripe-webhook
// Stripe Dashboard -> Webhooks -> endpoint:
//   https://<project-ref>.supabase.co/functions/v1/stripe-webhook
// Events: checkout.session.completed, customer.subscription.updated/deleted

import { createClient } from "jsr:@supabase/supabase-js@2";

const STRIPE_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";
const SUPABASE_URL  = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY   = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

/* Telegram admin alerts. Payout manual (duit masuk akaun Stripe orang lain
   dulu) bergantung pada notifikasi ini — admin perlu tahu reference +
   jumlah tepat untuk transfer balik kepada member. */
const TG_TOKEN  = Deno.env.get("TELEGRAM_ADMIN_BOT_TOKEN") ?? "";
const TG_CHAT   = Deno.env.get("TELEGRAM_ADMIN_CHAT_ID") ?? "";

async function alertAdmin(text: string) {
  if (!TG_TOKEN || !TG_CHAT) return;
  try {
    await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: TG_CHAT, text, disable_web_page_preview: true }),
    });
  } catch (_) {
    // Notifikasi gagal tidak boleh menggagalkan pemprosesan webhook.
  }
}

/* ---- Stripe signature verification (HMAC-SHA256, WebCrypto) ---- */
const enc = new TextEncoder();

async function verifyStripeSignature(payload: string, sigHeader: string, secret: string) {
  const parts = sigHeader.split(",");
  const ts = parts.find(p => p.startsWith("t="))?.slice(2);
  const v1 = parts.filter(p => p.startsWith("v1=")).map(p => p.slice(3));
  if (!ts || v1.length === 0) return false;

  // Reject replay > 5 min
  const age = Math.abs(Date.now() / 1000 - Number(ts));
  if (age > 300) return false;

  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`${ts}.${payload}`));
  const hex = [...new Uint8Array(mac)].map(b => b.toString(16).padStart(2, "0")).join("");
  return v1.some(s => s.length === hex.length && timingSafeEqual(s, hex));
}

function timingSafeEqual(a: string, b: string) {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

/* ---- Plan mapping: price id or metadata -> plan name ---- */
function planFromSession(session: any): string | null {
  const meta = session?.metadata || {};
  if (["free", "pro", "max"].includes(meta.plan)) return meta.plan;
  // Fallback: infer from line items / price nickname
  const desc = (session?.line_items?.data || []).map((li: any) =>
      `${li.price?.nickname ?? ""} ${li.description ?? ""}`).join(" ").toLowerCase();
  if (/\bmax\b/.test(desc)) return "max";
  if (/\bpro\b/.test(desc)) return "pro";
  if (/\bfree\b/.test(desc)) return "free";
  return null;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const payload = await req.text();
  const sig = req.headers.get("stripe-signature") ?? "";

  if (!STRIPE_SECRET) {
    return new Response(JSON.stringify({ error: "STRIPE_WEBHOOK_SECRET not set" }), { status: 500 });
  }
  if (!sig || !(await verifyStripeSignature(payload, sig, STRIPE_SECRET))) {
    return new Response(JSON.stringify({ error: "invalid signature" }), { status: 400 });
  }

  let event: any;
  try { event = JSON.parse(payload); } catch {
    return new Response(JSON.stringify({ error: "bad json" }), { status: 400 });
  }

  const sb = createClient(SUPABASE_URL, SERVICE_KEY, {
    auth: { persistSession: false },
  });

  const handled = [];
  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const s = event.data.object;
        const email = s.customer_details?.email ?? s.customer_email;
        const refId = s.client_reference_id ?? s.metadata?.user_id ?? null;
        const plan = planFromSession(s);
        if (!plan) break;

        // profiles.keyed by auth user id (no email column). The subscribe page
        // sends client_reference_id=<auth uid>, so prefer it. If Stripe dropped
        // it, look the user up by email through the auth admin API.
        let userId: string | null = refId;
        if (!userId && email) {
          const { data: list } = await sb.auth.admin.listUsers({ page: 1, perPage: 200 });
          const hit = (list?.users ?? []).find(u => u.email?.toLowerCase() === email.toLowerCase());
          userId = hit?.id ?? null;
        }
        if (!userId) break;

        const { error } = await sb.from("profiles").update({ plan }).eq("id", userId);
        if (error) throw error;
        handled.push(`checkout.session.completed -> ${email ?? userId} = ${plan}`);

        // Notifikasi admin: duit masuk akaun Stripe (nanti transfer manual
        // balik kepada member). Sertakan amount + currency supaya admin tak
        // perlu buka dashboard.
        const amount = s.amount_total ?? null;
        const currency = (s.currency ?? "").toUpperCase();
        await alertAdmin(
          `💰 <b>Stripe payment masuk</b>\n` +
          `Plan: <b>${plan.toUpperCase()}</b>\n` +
          `Member: ${email ?? userId}\n` +
          `Jumlah: ${amount != null ? `${(amount / 100).toFixed(2)} ${currency}` : "?"}\n` +
          `Session: ${s.id}\n` +
          `Bayar: ${s.payment_status ?? "?"}\n\n` +
          `👉 Transfer duit kepada member, kemudian sahkan dalam Stripe Dashboard.`
        );
        break;
      }

      case "customer.subscription.updated": {
        const s = event.data.object;
        const plan = planFromSession(s as any) ?? (s.status === "active" ? "pro" : null);
        const refId = s.metadata?.user_id ?? s.client_reference_id ?? null;
        if (!plan || !refId) break;
        const { error } = await sb.from("profiles").update({ plan }).eq("id", refId);
        if (error) throw error;
        handled.push(`subscription.updated -> ${refId} = ${plan}`);
        break;
      }

      case "customer.subscription.deleted": {
        const s = event.data.object;
        const refId = s.metadata?.user_id ?? s.client_reference_id ?? null;
        const email = s.customer_email ?? s.metadata?.email ?? null;
        let userId: string | null = refId;
        if (!userId && email) {
          const { data: list } = await sb.auth.admin.listUsers({ page: 1, perPage: 200 });
          userId = (list?.users ?? []).find(u => u.email?.toLowerCase() === email.toLowerCase())?.id ?? null;
        }
        if (!userId) break;
        const { error } = await sb.from("profiles").update({ plan: "free" }).eq("id", userId);
        if (error) throw error;
        handled.push(`subscription.deleted -> ${email ?? userId} = free`);
        await alertAdmin(
          `⚠️ <b>Langganan dibatalkan</b>\n` +
          `Member: ${email ?? userId}\n` +
          `Plan diturunkan ke FREE.\n` +
          `Subscription: ${s.id}`
        );
        break;
      }

      default:
        break;
    }
  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }

  return new Response(JSON.stringify({ received: true, handled, type: event.type }), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
});
