#!/usr/bin/env python3
"""XAUUSD StraddleReverse OCO/reverse bridge, 24/7.

Initial BUY_STOP + SELL_STOP. When one fills, remove the other and place a
reverse stop beyond the active position's entry/SL. Risk is 7% of current
balance per pending side; balance compounds after realised P/L.
"""
import importlib.util, json, os, sys, time, fcntl
from datetime import datetime, timedelta, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
STATE=HERE.parent/"state"/"straddle-reverse.json"
LOCK=Path("/tmp/straddle-reverse.lock")
SYMBOL="XAUUSD"; MAGIC=int(os.environ.get("REVERSE_MAGIC","777001"))
RISK=float(os.environ.get("REVERSE_RISK_PCT","7.0")); DIST=int(os.environ.get("REVERSE_DISTANCE_PTS","250")); SLPTS=int(os.environ.get("REVERSE_SL_PTS","250")); TPPTS=int(os.environ.get("REVERSE_TP_PTS","300")); REFRESH=int(os.environ.get("REVERSE_REFRESH_SEC","120")); MULT=float(os.environ.get("REVERSE_LOT_MULT","1.0")); MAXREV=int(os.environ.get("REVERSE_MAX","0")); SLEEP=2; MYT=timezone(timedelta(hours=8))
spec=importlib.util.spec_from_file_location("p",HERE/"mt5-pending.py"); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); MT5=mod.mt5

def log(x): print(datetime.now(MYT).strftime("%Y-%m-%dT%H:%M:%S"),x,flush=True)
def load():
 try:return json.loads(STATE.read_text())
 except:return {"depth":0,"pending_at":0,"last_pos":0}
def save(d): STATE.parent.mkdir(parents=True,exist_ok=True); t=STATE.with_suffix('.tmp'); t.write_text(json.dumps(d)); t.replace(STATE)
def mine(d,k):return [x for x in d.get(k,[]) if str(x.get('symbol','')).upper()==SYMBOL and int(x.get('magic',0) or 0)==MAGIC]
def lot(price,sl,balance,s):
 ts=float(s.get('tick_size') or s.get('point') or .01); tv=float(s.get('tick_value') or 0); step=float(s.get('vol_step') or .01); mn=float(s.get('vol_min') or step); mx=float(s.get('vol_max') or 100)
 loss=abs(price-sl)/ts*tv
 if loss<=0 or tv<=0:return 0
 return round(max(mn,min(mx,int((balance*RISK/100/loss)/step)*step)),2)
def cancel(orders):
 for o in orders: MT5({"action":"cancel","ticket":int(o['ticket'])}); log(f"CANCEL ticket={o['ticket']}")
def place(side,entry,sl,tp,l,s):
 r=MT5({"action":"place_limit","symbol":SYMBOL,"side":side,"entry":entry,"sl":sl,"tp":tp,"lot":l,"magic":MAGIC,"deviation":50,"comment":"REVERSE"}); log(f"PLACE {side} entry={entry} lot={l} risk={RISK}% ok={r.get('ok')} ticket={r.get('ticket')} ret={r.get('retcode')}"); return r
def cycle():
 st=load(); d=MT5({"action":"state"})
 if not d.get('ok'):log('MT5-ERR');return
 s=MT5({"action":"symbol","symbol":SYMBOL}); t=MT5({"action":"tick","symbol":SYMBOL})
 if not s.get('ok') or not t.get('ok'):return
 bal=float(d.get('balance') or 0); bid=float(t['bid']); ask=float(t['ask']); pt=float(s.get('point') or .01); lvl=float(s.get('stops_level') or 0)*pt
 pos=mine(d,'positions'); ords=mine(d,'orders')
 if pos:
  if ords:cancel(ords)
  # One active position: reverse pending only when none already exists.
  if not ords and (MAXREV<=0 or int(st.get('depth',0))<MAXREV):
   p=pos[0]; typ=int(p.get('type',0)); entry=float(p['price_open']); vol=float(p['volume']); sl_dist=max(SLPTS*pt,lvl+5*pt); revlot=round(vol*MULT,2)
   if typ==0: # BUY -> SellStop below entry
    ep=round(entry-sl_dist,2); sl=round(ep+sl_dist,2); tp=round(ep-TPPTS*pt,2) if TPPTS else 0; r=place('SELL',ep,sl,tp,revlot,s)
   else: # SELL -> BuyStop above entry
    ep=round(entry+sl_dist,2); sl=round(ep-sl_dist,2); tp=round(ep+TPPTS*pt,2) if TPPTS else 0; r=place('BUY',ep,sl,tp,revlot,s)
   if r.get('ok'):st['depth']=int(st.get('depth',0))+1;save(st)
  return
 if len(ords)==1:
  cancel(ords);st['pending_at']=0;save(st);return
 if len(ords)>=2:
  if REFRESH and time.time()-float(st.get('pending_at',time.time()))>=REFRESH:cancel(ords);st['pending_at']=0;save(st)
  return
 # fresh initial straddle
 dist=max(DIST*pt,lvl+(ask-bid)); sl_dist=max(SLPTS*pt,lvl+5*pt); tp_dist=TPPTS*pt if TPPTS else 0
 bp=round(ask+dist,2); sp=round(bid-dist,2); bl=lot(bp,bp-sl_dist,bal,s); sl=lot(sp,sp+sl_dist,bal,s)
 if not bl or not sl:log('LOT-SKIP');return
 rb=place('BUY',bp,round(bp-sl_dist,2),round(bp+tp_dist,2) if tp_dist else 0,bl,s)
 if not rb.get('ok'):return
 rs=place('SELL',sp,round(sp+sl_dist,2),round(sp-tp_dist,2) if tp_dist else 0,sl,s)
 if not rs.get('ok') and rb.get('ticket'):MT5({"action":"cancel","ticket":int(rb['ticket'])})
 if rs.get('ok'):st['pending_at']=time.time();save(st)
if __name__=='__main__':
 fd=open(LOCK,'w')
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except OSError:sys.exit(0)
 while True:
  try:cycle()
  except Exception as e:log(f"FATAL {type(e).__name__}: {e}")
  time.sleep(SLEEP)
