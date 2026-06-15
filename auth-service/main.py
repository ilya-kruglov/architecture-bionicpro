import base64
import hashlib
import os
import secrets
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError

from redis_client import redis_client

app = FastAPI()

# Разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],   # конкретный источник
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_EXTERNAL_URL = os.getenv("KEYCLOAK_EXTERNAL_URL", "http://localhost:8080")
REALM = os.getenv("KEYCLOAK_REALM", "reports-realm")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "reports-frontend")
REDIRECT_URI = "http://localhost:8000/auth/callback"
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", 3600))

@app.get("/auth/login")
async def login():
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    # Сохраняем verifier в Redis по state
    redis_client.setex(f"pkce:{state}", 600, code_verifier)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": "openid profile email"
    }
    # Используем ВНЕШНИЙ URL для редиректа браузера
    auth_url = f"{KEYCLOAK_EXTERNAL_URL}/realms/{REALM}/protocol/openid-connect/auth"
    redirect_url = f"{auth_url}?{urlencode(params)}"
    return RedirectResponse(redirect_url)

@app.get("/auth/callback")
async def callback(code: str, state: str, response: Response):
    # Восстанавливаем code_verifier
    code_verifier = redis_client.get(f"pkce:{state}")
    if not code_verifier:
        raise HTTPException(400, "Invalid state")

    # Обмен кода на токены
    token_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier.decode(),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            raise HTTPException(400, "Token exchange failed")
        tokens = resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    # Декодируем access_token для получения user_id (sub)
    try:
        payload = jwt.decode(access_token, None, options={"verify_signature": False})
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(400, "Invalid token")

    session_id = str(uuid.uuid4())
    # Храним refresh_token и access_token в Redis
    redis_client.hset(f"session:{session_id}", mapping={
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user_id": user_id
    })
    redis_client.expire(f"session:{session_id}", SESSION_TTL)

    # Устанавливаем cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=False,   # В production обязателен HTTPS (True)
        samesite="lax",
        max_age=SESSION_TTL,
        path="/"
    )
    # Редирект на фронтенд
    return RedirectResponse("http://localhost:3000")

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if session_id:
        # Получаем refresh_token для выхода из Keycloak (опционально)
        refresh = redis_client.hget(f"session:{session_id}", "refresh_token")
        if refresh:
            # Отзыв токена в Keycloak
            async with httpx.AsyncClient() as client:
                await client.post(f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/logout",
                                  data={"client_id": CLIENT_ID, "refresh_token": refresh.decode()})
        redis_client.delete(f"session:{session_id}")
    response.delete_cookie("session_id")
    return {"message": "Logged out"}

@app.get("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(401, "No session")
    session_data = redis_client.hgetall(f"session:{session_id}")
    if not session_data:
        raise HTTPException(401, "Invalid session")
    refresh_token = session_data.get(b"refresh_token", b"").decode()
    if not refresh_token:
        raise HTTPException(401, "No refresh token")

    token_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            raise HTTPException(401, "Refresh failed")
        new_tokens = resp.json()

    new_access = new_tokens["access_token"]
    new_refresh = new_tokens.get("refresh_token", refresh_token)
    # Обновляем в Redis
    redis_client.hset(f"session:{session_id}", mapping={
        "access_token": new_access,
        "refresh_token": new_refresh
    })
    # Ротация сессии (новый session_id)
    new_session_id = str(uuid.uuid4())
    redis_client.rename(f"session:{session_id}", f"session:{new_session_id}")
    redis_client.expire(f"session:{new_session_id}", SESSION_TTL)
    response.set_cookie(
        key="session_id",
        value=new_session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/"
    )
    return {"message": "Token refreshed"}

@app.get("/auth/user")
async def get_user(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(401)
    access_token = redis_client.hget(f"session:{session_id}", "access_token")
    if not access_token:
        raise HTTPException(401)
    # Проксируем запрос userinfo в Keycloak
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/userinfo",
            headers={"Authorization": f"Bearer {access_token.decode()}"}
        )
        if resp.status_code != 200:
            raise HTTPException(401)
    return resp.json()
