/* Shared helpers for the member pages */
function getMember(){
  try{ return JSON.parse(localStorage.getItem("tw_member")); }catch(_){ return null; }
}
function saveMember(m){
  try{ localStorage.setItem("tw_member", JSON.stringify(m)); }catch(_){}
}
function logOut(){
  try{ localStorage.removeItem("tw_member"); }catch(_){}
  location.href = "index.html";
}
function esc(v){
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function requireMember(){
  const m = getMember();
  if(!m){ location.href = "index.html#join"; return null; }
  return m;
}
function previewBanner(m){
  if(m && m.demo){
    const b = document.getElementById("previewBanner");
    if(b) b.hidden = false;
  }
}
