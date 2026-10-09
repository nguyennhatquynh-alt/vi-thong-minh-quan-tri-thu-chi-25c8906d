"""Máy chủ nhỏ của ứng dụng. Phục vụ giao diện, biểu tượng, chế độ offline, và đồng bộ dữ liệu về kho riêng."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

BASE = Path(__file__).parent
PUBLIC = BASE / "public"
DATA_FILE = Path(os.getenv("DATA_DIR", "/tmp")) / "app_records.json"
_LOCK = threading.Lock()

APP_ID = os.getenv("APP_ID", "").strip()
MOTHER = os.getenv("ROOT_MOTHERSHIP_URL", "").strip().rstrip("/")
APP_KEY = os.getenv("APP_KEY", "").strip()
ENROLL_CODE = os.getenv("ENROLL_CODE", "").strip()
_CAP_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_VALUE_BYTES = 60000
_STATE = {"enrolled": False}
_OWNER = {"t": 0.0, "hashes": None}
_PAIRS = {}
_JOIN_FAILS = []
_CLAIM_LOCK = threading.Lock()

app = FastAPI(title="App", docs_url=None, redoc_url=None)


# ---------- Kết nối kho dữ liệu riêng (chỉ dùng khóa của chính ứng dụng này) ----------
def _mother(method, path, body=None, timeout=15):
    if not MOTHER:
        return 0, {}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        MOTHER + path, data=data, method=method,
        headers={"Content-Type": "application/json", "X-App-Id": APP_ID,
                 "Authorization": "Bearer " + APP_KEY, "User-Agent": "gge-app/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            return exc.code, {}
    except Exception:
        return 0, {}


def _ensure_enrolled():
    if _STATE["enrolled"]:
        return True
    if not (MOTHER and APP_ID and APP_KEY):
        return False
    code, _ = _mother("GET", "/api/v1/tenant/data/ping")
    if code == 200:
        _STATE["enrolled"] = True
        return True
    if code == 0 or not ENROLL_CODE:
        return False
    code, _ = _mother("POST", "/api/v1/tenant/enroll",
                      {"app_id": APP_ID, "enroll_code": ENROLL_CODE, "app_key": APP_KEY})
    if code == 200:
        _STATE["enrolled"] = True
        return True
    return False


def _hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _owner_hashes(force=False):
    now = time.time()
    if not force and _OWNER["hashes"] is not None and now - _OWNER["t"] < 30:
        return _OWNER["hashes"]
    if not _ensure_enrolled():
        return None
    code, body = _mother("GET", "/api/v1/tenant/data/owner")
    if code != 200:
        return None
    hashes = []
    for row in body.get("records", []):
        if row.get("rec_id") == "devices":
            hashes = list((row.get("data") or {}).get("hashes", []))
    _OWNER["t"] = now
    _OWNER["hashes"] = hashes
    return hashes


def _save_owner_hashes(hashes):
    code, _ = _mother("PUT", "/api/v1/tenant/data/owner/devices", {"data": {"hashes": hashes[-10:]}})
    if code == 200:
        _OWNER["t"] = time.time()
        _OWNER["hashes"] = hashes[-10:]
        return True
    return False


def _check_owner(request):
    hashes = _owner_hashes()
    if hashes is None:
        raise HTTPException(503, "Kho dữ liệu riêng chưa sẵn sàng.")
    token = request.headers.get("x-owner-token", "")
    ok = False
    if token:
        digest = _hash(token)
        for known in hashes:
            if hmac.compare_digest(digest, str(known)):
                ok = True
    if not ok:
        raise HTTPException(401, "Thiết bị này chưa được liên kết.")


def _claim_sync():
    with _CLAIM_LOCK:
        hashes = _owner_hashes(force=True)
        if hashes is None:
            return 503, None
        if hashes:
            return 409, None
        token = secrets.token_urlsafe(24)
        if not _save_owner_hashes([_hash(token)]):
            return 503, None
        return 200, token


def _join_sync(code):
    now = time.time()
    _JOIN_FAILS[:] = [t for t in _JOIN_FAILS if now - t < 600]
    if len(_JOIN_FAILS) >= 5:
        return 429, None
    for key in [k for k, exp in _PAIRS.items() if exp < now]:
        _PAIRS.pop(key, None)
    if str(code or "").upper() not in _PAIRS:
        _JOIN_FAILS.append(now)
        return 401, None
    _PAIRS.pop(str(code).upper(), None)
    hashes = _owner_hashes(force=True)
    if hashes is None:
        return 503, None
    token = secrets.token_urlsafe(24)
    if not _save_owner_hashes(hashes + [_hash(token)]):
        return 503, None
    return 200, token


@app.on_event("startup")
def _startup():
    threading.Thread(target=_ensure_enrolled, daemon=True).start()


# ---------- Dữ liệu cục bộ đơn giản (giữ tương thích) ----------
def _load():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(rows):
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
@app.head("/")
async def index():
    return HTMLResponse((PUBLIC / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/manifest.json")
async def manifest():
    return Response((PUBLIC / "manifest.json").read_bytes(), media_type="application/manifest+json")


@app.get("/sw.js")
async def sw():
    return Response((PUBLIC / "sw.js").read_bytes(), media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/icon-{size}.png")
async def icon(size: int):
    f = PUBLIC / ("icon-%d.png" % (512 if size > 192 else 192))
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/png")


@app.get("/.well-known/assetlinks.json")
async def assetlinks():
    f = PUBLIC / "assetlinks.json"
    return Response(f.read_bytes() if f.exists() else b"[]", media_type="application/json")


@app.get("/api/data")
async def list_records():
    with _LOCK:
        return _load()


@app.post("/api/data")
async def create_record(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    with _LOCK:
        rows = _load()
        item = {"id": (max([r.get("id", 0) for r in rows]) + 1) if rows else 1}
        if isinstance(body, dict):
            item.update({k: v for k, v in body.items() if k != "id"})
        rows.append(item)
        _save(rows)
        return item


@app.delete("/api/data/{record_id}")
async def delete_record(record_id: int):
    with _LOCK:
        rows = [r for r in _load() if r.get("id") != record_id]
        _save(rows)
    return {"status": "SUCCESS"}


# ---------- Chủ sở hữu và liên kết thiết bị ----------
@app.get("/api/owner/state")
async def owner_state():
    hashes = await asyncio.to_thread(_owner_hashes)
    if hashes is None:
        raise HTTPException(503, "Kho dữ liệu riêng chưa sẵn sàng.")
    return {"claimed": bool(hashes)}


@app.post("/api/owner/claim")
async def owner_claim():
    code, token = await asyncio.to_thread(_claim_sync)
    if code == 200:
        return {"token": token}
    raise HTTPException(code, "Ứng dụng đã có chủ sở hữu." if code == 409 else "Kho dữ liệu riêng chưa sẵn sàng.")


@app.post("/api/owner/pair-code")
async def owner_pair_code(request: Request):
    await asyncio.to_thread(_check_owner, request)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    _PAIRS[code] = time.time() + 600
    return {"code": code, "valid_minutes": 10}


@app.post("/api/owner/join")
async def owner_join(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    code, token = await asyncio.to_thread(_join_sync, (body or {}).get("code", ""))
    if code == 200:
        return {"token": token}
    raise HTTPException(code, "Mã liên kết không đúng hoặc đã hết hạn.")


# ---------- Đồng bộ dữ liệu về kho riêng ----------
def _pull_items():
    code, body = _mother("GET", "/api/v1/tenant/export", timeout=25)
    if code != 200:
        return code, {}
    items = {}
    for row in body.get("records", []):
        if row.get("collection") == "cap":
            items[row.get("rec_id")] = row.get("data") or {}
    return 200, items


@app.get("/api/sync")
async def sync_pull(request: Request):
    await asyncio.to_thread(_check_owner, request)
    code, items = await asyncio.to_thread(_pull_items)
    if code != 200:
        raise HTTPException(503, "Chưa đọc được dữ liệu.")
    return {"items": items}


@app.put("/api/sync/{cap}")
async def sync_push(cap: str, request: Request):
    if not _CAP_RE.match(cap or ""):
        raise HTTPException(400, "Tên dữ liệu không hợp lệ.")
    await asyncio.to_thread(_check_owner, request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Dữ liệu không hợp lệ.")
    value = (body or {}).get("v")
    try:
        ts = int((body or {}).get("ts") or 0)
    except Exception:
        ts = 0
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > _MAX_VALUE_BYTES:
        raise HTTPException(413, "Dữ liệu quá lớn để đồng bộ.")
    code, _ = await asyncio.to_thread(
        _mother, "PUT", "/api/v1/tenant/data/cap/" + cap, {"data": {"v": value, "ts": ts}})
    if code == 200:
        return {"ok": True}
    raise HTTPException(402 if code == 402 else 503, "Chưa lưu được dữ liệu.")


@app.delete("/api/v1/account")
async def delete_account(request: Request):
    if MOTHER and APP_KEY:
        await asyncio.to_thread(_check_owner, request)
        await asyncio.to_thread(_mother, "DELETE", "/api/v1/tenant/account")
        _OWNER["hashes"] = None
    with _LOCK:
        _save([])
    return {"status": "SUCCESS", "message": "Đã xóa dữ liệu ứng dụng."}
