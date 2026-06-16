import base64
import hashlib
import os
import secrets
import uuid
import json
from urllib.parse import urlencode

import httpx
import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError
from redis_client import redis_client
from clickhouse_driver import Client

app = FastAPI()

# Разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Настройки Keycloak ===
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_EXTERNAL_URL = os.getenv("KEYCLOAK_EXTERNAL_URL", "http://localhost:8080")
REALM = os.getenv("KEYCLOAK_REALM", "reports-realm")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "reports-frontend")
REDIRECT_URI = "http://localhost:8000/auth/callback"
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", 3600))

# === Настройки S3 (Minio) ===
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "reports")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "http://localhost:8082")


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name='us-east-1',
        config=boto3.session.Config(signature_version='s3v4'),
    )


def ensure_bucket_exists():
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=MINIO_BUCKET)


@app.on_event("startup")
async def startup_event():
    ensure_bucket_exists()


def save_report_to_s3(user_id: str, period: str, data: list):
    client = get_s3_client()
    key = f"{user_id}/{period}.json"
    body = json.dumps(data).encode('utf-8')
    client.put_object(Bucket=MINIO_BUCKET, Key=key, Body=body, ContentType='application/json')
    return key


def get_report_from_s3(user_id: str, period: str):
    client = get_s3_client()
    key = f"{user_id}/{period}.json"
    try:
        response = client.get_object(Bucket=MINIO_BUCKET, Key=key)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return None
        raise


@app.get("/auth/login")
async def login():
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

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
    auth_url = f"{KEYCLOAK_EXTERNAL_URL}/realms/{REALM}/protocol/openid-connect/auth"
    redirect_url = f"{auth_url}?{urlencode(params)}"
    return RedirectResponse(redirect_url)


@app.get("/auth/callback")
async def callback(code: str, state: str, response: Response):
    code_verifier = redis_client.get(f"pkce:{state}")
    if not code_verifier:
        raise HTTPException(400, "Invalid state")

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
    try:
        payload = jwt.decode(access_token, None, options={"verify_signature": False})
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(400, "Invalid token")

    session_id = str(uuid.uuid4())
    redis_client.hset(f"session:{session_id}", mapping={
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user_id": user_id
    })
    redis_client.expire(f"session:{session_id}", SESSION_TTL)

    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/",
        domain="localhost"
    )
    return RedirectResponse("http://localhost:3000")


@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if session_id:
        refresh = redis_client.hget(f"session:{session_id}", "refresh_token")
        if refresh:
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
    redis_client.hset(f"session:{session_id}", mapping={
        "access_token": new_access,
        "refresh_token": new_refresh
    })
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
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/userinfo",
            headers={"Authorization": f"Bearer {access_token.decode()}"}
        )
        if resp.status_code != 200:
            raise HTTPException(401)
    return resp.json()


@app.get("/reports")
async def get_report(request: Request):
    # 1. Проверка аутентификации
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(401, "Not authenticated")
    user_id = redis_client.hget(f"session:{session_id}", "user_id")
    if not user_id:
        raise HTTPException(401, "User not found")
    user_id = user_id.decode()

    # 2. Параметры
    period = request.query_params.get("period", "last_7_days")

    # 3. Проверка наличия в S3
    report_from_s3 = get_report_from_s3(user_id, period)
    if report_from_s3 is not None:
        # Возвращаем ссылку на CDN
        cdn_url = f"{CDN_BASE_URL}/reports/{user_id}/{period}.json"
        return {"report_url": cdn_url}

    # 4. Генерация из ClickHouse
    date_from = "2026-01-01"  # упрощённо
    try:
        client = Client(host='clickhouse', port=9000, user='default', password='')
        query = """
            SELECT user_id, report_date, total_signals, avg_battery, unique_movements, customer_name, customer_email
            FROM reports.reports_mv
            WHERE user_id = %(user_id)s AND report_date >= %(date_from)s
            ORDER BY report_date DESC
        """
        rows = client.execute(query, {'user_id': user_id, 'date_from': date_from})
    except Exception as e:
        raise HTTPException(500, f"Database error: {str(e)}")

    if not rows:
        return {"message": "No data available for this user"}

    report_data = [
        {
            "date": str(row[1]),
            "total_signals": row[2],
            "avg_battery": row[3],
            "unique_movements": row[4],
            "customer_name": row[5],
            "customer_email": row[6],
        }
        for row in rows
    ]

    # 5. Сохраняем в S3
    try:
        save_report_to_s3(user_id, period, report_data)
    except Exception as e:
        print(f"Failed to save report to S3: {e}")

    # 6. Возвращаем ссылку на CDN и сами данные на случай, если сохранение не удалось
    cdn_url = f"{CDN_BASE_URL}/reports/{user_id}/{period}.json"
    return {"report_url": cdn_url, "data": report_data}
