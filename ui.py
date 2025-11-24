from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import requests
import json
import os

app = FastAPI()

templates = Jinja2Templates(directory="templates")

BACKEND = "http://localhost:8080/analyze/image"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """UIから受けたファイルを backend へ転送し、そのJSONをそのまま返す"""
    files = {"file": (file.filename, await file.read(), file.content_type)}
    try:
        r = requests.post(BACKEND, files=files, timeout=120)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "backend_unreachable", "message": str(e)})

    try:
        data = r.json()
        return JSONResponse(status_code=r.status_code, content=data)
    except ValueError:
        return JSONResponse(status_code=502, content={"error": "invalid_backend_response", "text": r.text[:2000]})
