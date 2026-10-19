#!/usr/bin/env python3
"""TraderWatch pending-payment notifier.
Polls Supabase payment_requests and alerts the admin once per request.
Email uses the existing Brevo SMTP secrets. Telegram is optional.
"""
import json, os, ssl, smtplib, urllib.parse, urllib.request, urllib.error
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone

BASE = Path.home() / '.secrets'
STATE = Path('/tmp/traderwatch-payment-alerts.json')
APPROVED_STATE = Path('/tmp/traderwatch-payment-approved-alerts.json')

def load(name):
    vals={}
    for line in (BASE/name).read_text().splitlines():
        line=line.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1); vals[k.strip()]=v.strip().strip('"').strip("'")
    return vals

def sb_get(path):
    s=load('supabase.env'); req=urllib.request.Request(s['SUPABASE_URL']+'/rest/v1/'+path,headers={'apikey':s['SUPABASE_SERVICE_KEY'],'Authorization':'Bearer '+s['SUPABASE_SERVICE_KEY']})
    with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode())

def send_email(subject, body):
    s=load('smtp.env'); m=EmailMessage(); m['From']=s['BREVO_SMTP_ADMIN_EMAIL']; m['To']=s['BREVO_SMTP_ADMIN_EMAIL']; m['Subject']=subject; m.set_content(body)
    with smtplib.SMTP(s['BREVO_SMTP_HOST'],int(s['BREVO_SMTP_PORT']),timeout=25) as c:
        c.starttls(context=ssl.create_default_context()); c.login(s['BREVO_SMTP_USER'],s['BREVO_SMTP_PASSWORD']); c.send_message(m)

def send_telegram(text):
    try:
        s=load('telegram.env'); token=s.get('TELEGRAM_BOT_TOKEN'); chat=s.get('TELEGRAM_ADMIN_CHAT_ID')
        if not token or not chat: return False
        url='https://api.telegram.org/bot'+token+'/sendMessage?'+urllib.parse.urlencode({'chat_id':chat,'text':text})
        with urllib.request.urlopen(url,timeout=20) as r: return r.status==200
    except Exception: return False

def main():
    rows=sb_get('payment_requests?select=id,email,name,plan,amount_usd,amount_myr,reference,status,created_at,reviewed_at&status=in.(pending,approved)&order=created_at.asc&limit=100')
    try: seen=set(json.loads(STATE.read_text()))
    except Exception: seen=set()
    try: approved_seen=set(json.loads(APPROVED_STATE.read_text()))
    except Exception: approved_seen=set()
    changed=False; approved_changed=False
    for r in rows:
        key=str(r['id'])
        if r['status'] == 'approved':
            if key in approved_seen: continue
            text=(f"TraderWatch payment approved ✅\n\n"
                  f"Request ID: {r['id']}\n"
                  f"Email: {r['email']}\n"
                  f"Plan: {r['plan'].upper()}\n"
                  f"Status: APPROVED\n"
                  f"Reference: {r['reference']}\n"
                  f"Access is now active.")
            send_email('TraderWatch: '+r['plan'].upper()+' approved ✅',text)
            send_telegram(text)
            approved_seen.add(key); approved_changed=True
            print('approval-alerted request',key,r['email'],r['plan'])
            continue
        if key in seen: continue
        text=(f"TraderWatch payment pending\nPlan: {r['plan'].upper()}\nMember: {r.get('name') or '-'}\nEmail: {r['email']}\nAmount: RM {r.get('amount_myr') or '-'} / ${r.get('amount_usd') or '-'}\nReference: {r['reference']}\nOpen: https://aidilbahaman.github.io/Traderwatch/admin.html")
        send_email('TraderWatch: pending '+r['plan'].upper()+' approval',text)
        send_telegram(text)
        seen.add(key); changed=True
        print('alerted request',key,r['email'],r['plan'])
    if changed: STATE.write_text(json.dumps(sorted(seen))); STATE.chmod(0o600)
    if approved_changed: APPROVED_STATE.write_text(json.dumps(sorted(approved_seen))); APPROVED_STATE.chmod(0o600)
    print('rows=',len(rows),'new_pending_alerts=',sum(1 for r in rows if r['status']=='pending' and str(r['id']) in seen),'new_approval_alerts=',sum(1 for r in rows if r['status']=='approved' and str(r['id']) in approved_seen))

if __name__=='__main__': main()
