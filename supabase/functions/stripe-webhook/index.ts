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

        // NOTIFY SAHAJA. Plan TIDAK auto-upgrade — owner upgrade client
        // secara manual selepas semak bayaran (akaun Stripe milik rakan
        // kongsi, jadi duit perlu disahkan dulu).
        // Cache plan supaya alert boleh tunjuk tier yang十六条.
        const amount = s.amount_total ?? null;
        const currency = (s.currency ?? "").toUpperCase();
        handled.push(`checkout.session.completed ${email ?? userId} -> notify ${plan}`);

        const { data: prof } = await sb.from("profiles")
          .select("plan,name").eq("id", userId).maybeSingle();
        const nowPlan = prof?.plan ?? "free";

        await alertAdmin(
          `💰 <b>Stripe payment masuk</b>\n` +
          `Tier dibeli: <b>${plan.toUpperCase()}</b>\n` +
          `Member: ${prof?.name || "—"} (${email ?? userId})\n` +
          `Plan sekarang: <b>${String(nowPlan).toUpperCase()}</b>\n` +
          `Jumlah: ${amount != null ? `${(amount / 100).toFixed(2)} ${currency}` : "?"}\n` +
          `Session: ${s.id}\n` +
          `Status: ${s.payment_status ?? "?"}\n\n` +
          `👉 Semak Stripe Dashboard, transfer kepada KAU, kemudian upgrade tier client secara manual.`
        );
        break;
      }

      case "customer.subscription.updated": {
        const s = event.data.object;
        const plan = planFromSession(s as any) ?? (s.status === "active" ? "pro" : null);
        const refId = s.metadata?.user_id ?? s.client_reference_id ?? null;
        if (!plan || !refId) break;
        handled.push(`subscription.updated ${refId} -> notify ${plan}`);
        await alertAdmin(
          `🔄 <b>Langganan dikemas kini (Stripe)</b>\n` +
          `User: ${refId}\n` +
          `Tier dalam bayaran: <b>${plan.toUpperCase()}</b>\n` +
          `Status: ${s.status ?? "?"}\n\n` +
          `👉 Semak Stripe Dashboard. Upgrade/downgrade tier client secara manual jika perlu.`
        );
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
        // NOTIFY SAHAJA — downgrade juga manual supaya owner boleh semak
        // dulu (ada kalanya refund belum selesai proses).
        handled.push(`subscription.deleted ${email ?? userId} -> notify`);
        await alertAdmin(
          `⚠️ <b>Langganan dibatalkan (Stripe)</b>\n` +
          `Member: ${email ?? userId}\n` +
          `Subscription: ${s.id}\n\n` +
          `👉 Semak Stripe Dashboard. Downgrade tier client secara manual jika perlu.`
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
