/* Shared helpers: Supabase login + member profile */
const sb = window.supabase.createClient(CONFIG.supabaseUrl, CONFIG.supabaseKey);

async function loadMember(){
  const { data } = await sb.auth.getSession();
  const session = data && data.session;
  if(!session) return null;
  const u = session.user;
  let plan = "free";
  let name = (u.user_metadata && u.user_metadata.name) || "";
  let telegram_chat_id = null;
  try{
    const r = await sb.from("profiles").select("name,plan,telegram_chat_id").eq("id", u.id).single();
    if(r.data){ plan = r.data.plan; name = r.data.name || name; telegram_chat_id = r.data.telegram_chat_id; }
  }catch(_){}
  return { id:u.id, email:u.email, name: name || (u.email || "").split("@")[0], plan:plan, telegram_chat_id:telegram_chat_id };
}
function requireMember(returnTo){
  const m = loadMember();
  return m.then(member=>{
    if(!member){
      const target = returnTo || location.pathname + location.search;
      location.href = "login.html?next=" + encodeURIComponent(target);
      return null;
    }
    return member;
  });
}
async function logOut(){
  // Clear local auth state first so a failed network call cannot leave a
  // usable session behind, then ask Supabase to revoke it server-side.
  try{
    Object.keys(localStorage).forEach(k=>{
      if(/^sb-.*-auth-token/.test(k)) localStorage.removeItem(k);
    });
    Object.keys(sessionStorage).forEach(k=>{
      if(/^sb-.*-auth-token/.test(k)) sessionStorage.removeItem(k);
    });
  }catch(_){}
  try{ await sb.auth.signOut({ scope: "global" }); }
  catch(_){ try{ await sb.auth.signOut({ scope: "local" }); }catch(__){} }
  location.replace("login.html?loggedout=1");
}
function previewBanner(){}
function esc(v){
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
