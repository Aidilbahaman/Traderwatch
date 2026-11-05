"""Fasa 4 — Signal lifecycle (spec §3.1 langkah 7, §3.5).

Prinsip:
  - Rekod analysis run KEKAL (immutable) — signal lama kekal boleh dijelaskan.
  - Outcome ditulis BERASINGAN, tidak mengubah rekod asal.
  - Setiap tindakan diaudit.
  - Private mode: tiada akses authenticated; admin guna service key.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SECRETS = Path.home() / ".secrets" / "supabase.env"


def _sb():
    sec = {}
    for l in SECRETS.read_text().splitlines():
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec["SUPABASE_URL"].rstrip("/"), sec["SUPABASE_SERVICE_KEY"]


def _req(table, method="GET", body=None, params="", prefer=None, timeout=25):
    url, key = _sb()
    full = f"{url}/rest/v1/{table}{params}"
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(full, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]
    except Exception as ex:
        return 0, f"{type(ex).__name__}: {ex}"


def snapshot_hash(payload):
    """Hash input snapshot — supaya signal boleh dihasilkan semula (spec §1.2 #5)."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:32]


def save_run(analysis, snapshot=None):
    """Simpan analysis run kekal. Pulangkan (ok, run_id, error)."""
    row = {
        "symbol": analysis["symbol"],
        "as_of": analysis["as_of"],
        "strategy_version": analysis.get("strategy_version", "?"),
        "feature_version": analysis.get("feature_version", "?"),
        "regime": analysis.get("regime"),
        "regime_confidence": analysis.get("regime_confidence"),
        "bias": analysis.get("bias"),
        "directional_score": analysis.get("directional_score"),
        "coverage_score": analysis.get("coverage_score"),
        "conflict_score": analysis.get("conflict_score"),
        "decision": analysis.get("decision"),
        "reason_codes": analysis.get("reason_codes", []),
        "evidence": analysis.get("evidence", {}),
        "setup": analysis.get("setup", {}),
        "gates": analysis.get("gates", {}),
        "data_quality": analysis.get("data_quality", {}),
        "input_snapshot_hash": snapshot_hash(snapshot or analysis),
    }
    code, out = _req("cf_analysis_runs", "POST", row, prefer="return=representation")
    if code in (200, 201) and isinstance(out, list) and out:
        return True, out[0].get("id"), None
    return False, None, f"HTTP {code}: {out}"


def _expiry(as_of, hours):
    """Kira masa luput dari as_of (UTC)."""
    try:
        d = datetime.fromisoformat(str(as_of))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
    except Exception:
        d = datetime.now(timezone.utc)
    return (d + timedelta(hours=hours)).isoformat()


def create_signal(analysis, run_id=None, expires_hours=4):
    """Buat signal DRAFT dari analysis. WAIT/NO_TRADE tidak diterbitkan."""
    dec = analysis.get("decision")
    if dec not in ("BUY", "SELL"):
        return False, None, f"decision {dec} bukan BUY/SELL — tiada signal"
    s = analysis.get("setup") or {}
    now = datetime.now(timezone.utc)
    row = {
        "analysis_run_id": run_id,
        "symbol": analysis["symbol"],
        "signal_type": dec,
        "status": "DRAFT",
        "entry_min": s.get("entry"),
        "entry_max": s.get("entry"),
        "stop_loss": s.get("sl"),
        "take_profit_1": s.get("tp"),
        "risk_reward": s.get("risk_reward"),
        "confidence_label": analysis.get("confidence_label"),
        "summary": f"{dec} {analysis['symbol']} — {analysis.get('regime')} regime",
        "valid_from": analysis["as_of"],
        "expires_at": _expiry(analysis["as_of"], expires_hours),
    }
    code, out = _req("cf_signals", "POST", row, prefer="return=representation")
    if code in (200, 201) and isinstance(out, list) and out:
        sid = out[0].get("id")
        audit(sid, "CREATED", details={"decision": dec})
        return True, sid, None
    return False, None, f"HTTP {code}: {out}"


def audit(signal_id, event_type, actor_id=None, details=None):
    """Tulis log audit. Kegagalan audit TIDAK boleh gagalkan operasi utama."""
    try:
        _req("cf_signal_audits", "POST",
             {"signal_id": signal_id, "event_type": event_type,
              "actor_id": actor_id, "details": details or {}},
             prefer="return=minimal")
        return True
    except Exception:
        return False


def publish(signal_id, actor_id, require_admin=True):
    """Terbitkan signal (admin sahaja). Status DRAFT -> PUBLISHED."""
    if require_admin and not actor_id:
        return False, "actor_id wajib untuk publish"
    # Semak status semasa — hanya DRAFT boleh terbit
    code, rows = _req("cf_signals", "GET", params=f"?id=eq.{signal_id}&select=status,signal_type")
    if code != 200 or not rows:
        return False, f"signal tidak dijumpai (HTTP {code})"
    cur = rows[0]
    if cur["status"] != "DRAFT":
        return False, f"status {cur['status']} tidak boleh diterbitkan (perlu DRAFT)"
    if cur["signal_type"] not in ("BUY", "SELL"):
        return False, f"signal_type {cur['signal_type']} tidak diterbitkan"
    now = datetime.now(timezone.utc).isoformat()
    code, out = _req("cf_signals", "PATCH",
                     {"status": "PUBLISHED", "published_at": now,
                      "published_by": str(actor_id)},
                     params=f"?id=eq.{signal_id}", prefer="return=representation")
    if code in (200, 204):
        audit(signal_id, "PUBLISHED", actor_id, {"at": now})
        return True, None
    return False, f"HTTP {code}: {out}"


def cancel(signal_id, actor_id, reason):
    """Batalkan signal. Sebab WAJIB (spec §3.2)."""
    if not reason or not str(reason).strip():
        return False, "sebab pembatalan wajib"
    code, out = _req("cf_signals", "PATCH",
                     {"status": "CANCELLED"},
                     params=f"?id=eq.{signal_id}", prefer="return=minimal")
    if code in (200, 204):
        audit(signal_id, "CANCELLED", actor_id, {"reason": reason})
        return True, None
    return False, f"HTTP {code}: {out}"


def record_outcome(signal_id, outcome, actor_id=None):
    """Rekod keputusan (TP/SL). TIDAK mengubah rekod signal asal (spec §3.1 #7)."""
    code, out = _req("cf_signals", "PATCH",
                     {"outcome": outcome},
                     params=f"?id=eq.{signal_id}", prefer="return=minimal")
    if code in (200, 204):
        audit(signal_id, "OUTCOME_RECORDED", actor_id, outcome)
        return True, None
    return False, f"HTTP {code}: {out}"


def get_signals(status=None, symbol=None, limit=50):
    """Senarai signal. Private mode — admin sahaja (service key)."""
    parts = [f"limit={limit}", "order=created_at.desc"]
    if status:
        parts.append(f"status=eq.{status}")
    if symbol:
        parts.append(f"symbol=eq.{symbol.upper()}")
    code, rows = _req("cf_signals", "GET", params="?" + "&".join(parts))
    return rows if code == 200 else []


def get_audit(signal_id):
    code, rows = _req("cf_signal_audits", "GET",
                      params=f"?signal_id=eq.{signal_id}&order=event_time.asc")
    return rows if code == 200 else []
