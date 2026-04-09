# ================================================================
# SERVIDOR — BOT MU PRO API
# Instalar: pip install fastapi uvicorn python-multipart requests opencv-python-headless numpy
# Correr:   uvicorn server:app --host 0.0.0.0 --port 8000
# ================================================================

import os
import json
import hmac
import hashlib
import base64
import datetime
import requests

import cv2 as cv
import numpy as np
from fastapi import FastAPI, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

# ── CONFIG ──────────────────────────────────────────────────────
SECRET_KEY         = "BotMUPro_2024_X9#mK$vL@pQ8!rZ3wN"  # cambia esto
HELPER_IMG         = "references/mu-helper-running.png"
SAFEZONE_IMG       = "references/mu-safe-zone.png"
CONFIANZA_HELPER   = 0.9
CONFIANZA_SAFEZONE = 0.75
LICENCIAS_FILE     = "data/licencias.json"
TELEGRAM_FILE      = "data/telegram.json"

# ── HELPERS ─────────────────────────────────────────────────────
def cargar_json(ruta, default):
    if not os.path.exists(ruta):
        return default
    with open(ruta) as f:
        return json.load(f)

def guardar_json(ruta, data):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w") as f:
        json.dump(data, f, indent=4)

def verificar_licencia(hwid: str) -> tuple[bool, str]:
    licencias = cargar_json(LICENCIAS_FILE, {})
    if hwid not in licencias:
        return False, "HWID sin licencia."
    expira = datetime.datetime.strptime(licencias[hwid]["expira"], "%Y-%m-%d")
    if datetime.datetime.utcnow() > expira:
        return False, "Licencia vencida."
    dias = (expira - datetime.datetime.utcnow()).days
    return True, f"OK — {dias} días restantes"

def buscar_template(img_bgr, ruta, confianza):
    if not os.path.exists(ruta):
        return False, 0.0
    template  = cv.imread(ruta)
    if template is None:
        return False, 0.0
    resultado = cv.matchTemplate(img_bgr, template, cv.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv.minMaxLoc(resultado)
    return max_val >= confianza, round(float(max_val), 3)

def send_telegram(token, chat_id, mensaje, foto_bytes=None):
    if foto_bytes:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        requests.post(url, data={"chat_id": chat_id, "caption": mensaje},
                      files={"photo": ("muerte.png", foto_bytes)}, timeout=10)
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": mensaje}, timeout=10)

# ── ENDPOINTS ───────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "BOT MU PRO API activa"}

# Verificar licencia
@app.get("/check-license")
def check_license(hwid: str = Header(...)):
    valida, msg = verificar_licencia(hwid)
    return {"valid": valida, "message": msg}

# Análisis de imagen — endpoint principal
@app.post("/analyze")
async def analyze(
    nick: str = Header(...),
    hwid: str = Header(...),
    token: str = Header(...),
    chat_id: str = Header(...),
    file: UploadFile = File(...)
):
    # 1. Verificar licencia
    valida, msg = verificar_licencia(hwid)
    if not valida:
        raise HTTPException(status_code=403, detail=msg)

    # 2. Leer imagen enviada por el cliente
    contenido = await file.read()
    arr = np.frombuffer(contenido, dtype=np.uint8)
    img = cv.imdecode(arr, cv.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Imagen inválida.")

    # 3. PASO 1 — buscar helper
    helper_ok, helper_match = buscar_template(img, HELPER_IMG, CONFIANZA_HELPER)
    print(f"[{nick}] Helper match={helper_match} → {'OK' if helper_ok else 'AUSENTE'}")

    if helper_ok:
        return {"status": "alive", "helper": helper_match}

    # 4. PASO 2 — helper ausente, buscar safe zone
    safe_ok, safe_match = buscar_template(img, SAFEZONE_IMG, CONFIANZA_SAFEZONE)
    print(f"[{nick}] SafeZone match={safe_match} → {'MUERTE' if safe_ok else 'no detectada'}")

    if safe_ok:
        # Mandar alerta Telegram desde el servidor
        send_telegram(token, chat_id,
                      f"💀 {nick} ha muerto!",
                      foto_bytes=contenido)
        return {"status": "dead", "safe_match": safe_match}

    return {"status": "helper_off", "safe_match": safe_match}

# ── ADMIN: gestionar licencias ───────────────────────────────────

@app.post("/admin/add-license")
def add_license(
    hwid: str,
    dias: int = 30,
    admin_key: str = Header(...)
):
    if admin_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="No autorizado.")
    expira = (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).strftime("%Y-%m-%d")
    licencias = cargar_json(LICENCIAS_FILE, {})
    licencias[hwid] = {"expira": expira, "creada": datetime.datetime.utcnow().strftime("%Y-%m-%d")}
    guardar_json(LICENCIAS_FILE, licencias)
    return {"ok": True, "hwid": hwid, "expira": expira}

@app.delete("/admin/remove-license")
def remove_license(hwid: str, admin_key: str = Header(...)):
    if admin_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="No autorizado.")
    licencias = cargar_json(LICENCIAS_FILE, {})
    if hwid in licencias:
        del licencias[hwid]
        guardar_json(LICENCIAS_FILE, licencias)
    return {"ok": True}

@app.get("/admin/licenses")
def list_licenses(admin_key: str = Header(...)):
    if admin_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="No autorizado.")
    return cargar_json(LICENCIAS_FILE, {})
