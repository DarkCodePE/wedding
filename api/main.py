import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
import redis
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets

load_dotenv()

app = FastAPI()

# Habilitar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir todas las orígenes. Cambia esto para permitir solo orígenes específicos.
    allow_credentials=True,
    allow_methods=["*"],  # Permitir todos los métodos HTTP. Cambia esto para permitir solo métodos específicos.
    allow_headers=["*"],  # Permitir todas las cabeceras. Cambia esto para permitir solo cabeceras específicas.
)

# Configuración de Upstash Redis
redis_client = redis.Redis(
    host=os.getenv('UPSTASH_REDIS_HOST', 'vital-tetra-57649.upstash.io'),
    port=int(os.getenv('UPSTASH_REDIS_PORT', 6379)),
    password=os.getenv('UPSTASH_REDIS_PASSWORD'),
    ssl=True,
    decode_responses=True
)

# Configuración de Gmail SMTP
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
# Obtener el dominio de Vercel de las variables de entorno
VERCEL_URL = os.getenv("VERCEL_URL", "wedding-sigma-inky.vercel.app")
class RSVPData(BaseModel):
    name: str
    email: str


def send_confirmation_email(email: str, confirmation_link: str):
    subject = "Confirma tu asistencia a nuestra boda"
    body = f"Por favor, confirma tu asistencia haciendo clic en este enlace: {confirmation_link}"

    message = MIMEMultipart()
    message["From"] = GMAIL_ADDRESS
    message["To"] = email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.send_message(message)

@app.post("/api/submit-rsvp")
async def submit_rsvp(rsvp: RSVPData):
    try:
        # Crear una clave única para cada RSVP
        rsvp_key = f"rsvp:{rsvp.email}"

        # Generar token único para confirmación
        token = secrets.token_urlsafe(32)

        # Guardar los datos del RSVP en Redis
        redis_client.hset(rsvp_key, mapping={
            "name": rsvp.name,
            "email": rsvp.email,
            "timestamp": redis_client.time()[0],  # Tiempo actual del servidor
            "confirmed": "false",
            "confirmation_token": token
        })

        # Agregar el email a un set de todos los RSVPs
        redis_client.sadd("all_rsvps", rsvp.email)

        # Generar enlace de confirmación usando el dominio de Vercel
        confirmation_link = f"https://{VERCEL_URL}/api/confirm-rsvp/{token}"

        # Enviar email de confirmación
        send_confirmation_email(rsvp.email, confirmation_link)

        return {"message": "RSVP registrado con éxito. Por favor, revisa tu email para confirmar tu asistencia."}
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=f"Error de Redis: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado: {str(e)}")

@app.get("/api/confirm-rsvp/{token}")
async def confirm_rsvp(token: str):
    try:
        # Buscar el RSVP con el token dado
        for key in redis_client.scan_iter("rsvp:*"):
            rsvp_data = redis_client.hgetall(key)
            if rsvp_data.get("confirmation_token") == token:
                # Actualizar el estado a confirmado
                redis_client.hset(key, "confirmed", "true")
                return FileResponse("confirmation.html")

        raise HTTPException(status_code=400, detail="Token inválido o expirado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/rsvp-count")
async def get_rsvp_count():
    try:
        count = redis_client.scard("all_rsvps")
        return {"count": count}
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=f"Error de Redis: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado: {str(e)}")


@app.get("/api/check-rsvp/{email}")
async def check_rsvp(email: str):
    try:
        rsvp_key = f"rsvp:{email}"
        rsvp_data = redis_client.hgetall(rsvp_key)
        if rsvp_data:
            return {"registered": True, "name": rsvp_data.get("name")}
        else:
            return {"registered": False}
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=f"Error de Redis: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado: {str(e)}")


@app.get("/api/test-connection")
async def test_connection():
    try:
        redis_client.set('foo', 'bar')
        value = redis_client.get('foo')
        return {"message": f"Conexión exitosa. Valor de prueba: {value}"}
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=f"Error de conexión a Redis: {str(e)}")



if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)