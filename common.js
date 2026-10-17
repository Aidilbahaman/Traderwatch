/* Shared helpers: Supabase login + member profile */
const sb = window.supabase.createClient(CONFIG.supabaseUrl, CONFIG.supabaseKey);

async function loadMember(){
  const { data } = await sb.auth.getSession();
  const session = data && data.session;
  if(!session) return null;
  const u = session.user;
  let plan = "free";
  let name = (u.user_metadata && u.user_metadata.name) || "";
  try{
    const r = await sb.from("profiles").select("name,plan").eq("id", u.id).single();
    if(r.data){ plan = r.data.plan; name = r.data.name || name; }
  }catch(_){}
  return { id:u.id, email:u.email, name: name || (u.email || "").split("@")[0], plan:plan };
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
  await sb.auth.signOut();
  location.href = "index.html";
}
function previewBanner(){}
function esc(v){
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
