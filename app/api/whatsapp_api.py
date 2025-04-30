import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from dotenv import load_dotenv
import asyncio
import uvicorn
import json
from datetime import datetime
import sys
from pathlib import Path
import httpx
import time
from sqlalchemy.sql import text as sql_text

# Agregar el directorio raíz al path para poder importar desde app
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from app.services.test_agent import TestAIAgent
from app.database.database import async_session, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.db_utils import (
    get_menu_from_db, get_locales_from_db, process_order,
    update_user_data, get_user_data, _format_order_confirmation,
    save_message, mark_conversation_for_human, is_in_human_mode
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()
logger.info("Variables de entorno cargadas")

# Diccionario para almacenar los agentes por usuario y su última actividad
user_agents = {}  # {usuario_id: (TestAIAgent, last_seen_timestamp)}

# Variables globales para menú y locales
menu_data = None
locales_data = None

# Constante para el tiempo de inactividad (24 horas en segundos)
INACTIVITY_THRESHOLD = 60 * 60 * 24

async def cleanup_inactive_agents():
    """
    Limpia los agentes que han estado inactivos por más de 24 horas.
    """
    current_time = time.time()
    inactive_users = []
    
    # Identificar usuarios inactivos
    for usuario_id, (agent, last_seen) in user_agents.items():
        if current_time - last_seen > INACTIVITY_THRESHOLD:
            inactive_users.append(usuario_id)
    
    # Eliminar usuarios inactivos
    for usuario_id in inactive_users:
        del user_agents[usuario_id]
    
    if inactive_users:
        logger.info(f"Limpieza de agentes completada: {len(inactive_users)} agentes eliminados por inactividad")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Base de datos inicializada")
    async with async_session() as session:
        global menu_data, locales_data
        menu_data = await get_menu_from_db(session)
        locales_data = await get_locales_from_db(session)
        if not menu_data:
            logger.warning("No se pudo obtener el menú de la base de datos")
    yield
    logger.info("Cerrando aplicación...")

app = FastAPI(lifespan=lifespan)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

async def send_whatsapp_message_cloud(to_number: str, message_body: str):
    """
    Envía un mensaje usando la WhatsApp Cloud API
    """
    # Eliminar cualquier prefijo de whatsapp: y el signo +
    cleaned_number = to_number.replace('whatsapp:', '').replace('+', '')
    
    # Eliminar cualquier caracter no numérico
    cleaned_number = ''.join(filter(str.isdigit, cleaned_number))
    
    # Para números de Argentina, si viene con 549, cambiarlo a 54
    if cleaned_number.startswith("549"):
        cleaned_number = "54" + cleaned_number[3:]
    
    logger.info(f"Número original: {to_number}")
    logger.info(f"Número limpio para API: {cleaned_number}")
    
    url = f"https://graph.facebook.com/{os.getenv('WSP_API_VERSION')}/{os.getenv('WSP_PHONE_NUMBER_ID')}/messages"
    
    headers = {
        "Authorization": f"Bearer {os.getenv('WSP_ACCESS_TOKEN')}",
        "Content-Type": "application/json"
    }
    
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": cleaned_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_body
        }
    }
    
    logger.info(f"Enviando mensaje a WhatsApp API")
    logger.info(f"Datos: {json.dumps(data, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response_json = response.json()
            
            if response.status_code == 200:
                logger.info(f"Mensaje enviado exitosamente: {json.dumps(response_json, indent=2)}")
            else:
                logger.error(f"Error al enviar mensaje. Status: {response.status_code}")
                logger.error(f"Respuesta: {json.dumps(response_json, indent=2)}")
            
            return response_json
    except Exception as e:
        logger.error(f"Excepción al enviar mensaje: {str(e)}")
        raise

async def get_media_url(media_id: str, media_type: str = "image"):
    """
    Obtiene la URL de un archivo multimedia usando la API de WhatsApp Cloud.
    
    Args:
        media_id (str): ID del archivo multimedia
        media_type (str): Tipo de medio (image, video, document, audio)
    
    Returns:
        str: URL del archivo multimedia con token de acceso o None si hay error
    """
    url = f"https://graph.facebook.com/{os.getenv('WSP_API_VERSION')}/{media_id}"
    headers = {
        "Authorization": f"Bearer {os.getenv('WSP_LONG_LIVED_ACCESS_TOKEN')}",  # Usar token de larga duración
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            # Obtener la URL del media
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                media_data = response.json()
                media_url = media_data.get("url")
                logger.info(f"Media data obtenida para {media_type}: {json.dumps(media_data, indent=2)}")
                
                if media_url:
                    # Agregar el token de acceso a la URL
                    access_token = os.getenv('WSP_LONG_LIVED_ACCESS_TOKEN')
                    if '?' in media_url:
                        media_url += f"&access_token={access_token}"
                    else:
                        media_url += f"?access_token={access_token}"
                    
                    logger.info(f"URL de {media_type} con token de acceso generada")
                    return media_url
                
                logger.error("No se pudo obtener la URL del medio")
                return None
            else:
                logger.error(f"Error obteniendo media URL. Status: {response.status_code}")
                logger.error(f"Respuesta: {response.text}")
                return None
    except Exception as e:
        logger.error(f"Excepción al obtener media URL: {str(e)}")
        return None

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        return int(params.get("hub.challenge"))
    return {"status": "error", "message": "Verificación fallida"}

@app.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db)
):
    try:
        payload = await request.json()
        logger.info(f"Datos completos recibidos en webhook: {json.dumps(payload, indent=2)}")

        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "ok", "message": "No hay mensajes nuevos"}

        message = messages[0]
        from_number = message["from"]
        message_type = message.get("type", "text")
        
        # Inicializar variables para el mensaje
        body = ""
        media_url = None
        
        # Procesar según el tipo de mensaje
        if message_type == "text":
            body = message.get("text", {}).get("body", "")
        elif message_type in ["image", "video", "document", "audio"]:
            # Manejar diferentes tipos de media
            media_data = message.get(message_type, {})
            media_id = media_data.get("id")
            
            # Establecer el texto del mensaje según el tipo
            media_texts = {
                "image": "[Imagen]",
                "video": "[Video]",
                "document": "[Documento]",
                "audio": "[Audio]"
            }
            body = media_texts.get(message_type, f"[{message_type.capitalize()}]")
            
            # Obtener caption si existe
            caption = media_data.get("caption", "")
            if caption:
                body = f"{body} - {caption}"
            
            if media_id:
                media_url = await get_media_url(media_id, message_type)
                if media_url:
                    logger.info(f"URL de {message_type} obtenida: {media_url}")
                else:
                    logger.error(f"No se pudo obtener la URL del {message_type}")
        else:
            logger.warning(f"Tipo de mensaje no soportado: {message_type}")
            return {"status": "ok", "message": "Tipo de mensaje no soportado"}

        if not body and not media_url:
            logger.warning("Mensaje recibido sin contenido. Ignorando.")
            return {"status": "ok", "message": "Mensaje sin contenido"}

        logger.info(f"Mensaje recibido de {from_number}: {body}")
        if media_url:
            logger.info(f"Media URL: {media_url}")

        # Registrar o encontrar usuario
        user_query = sql_text("""
            WITH new_user AS (
                INSERT INTO hatsu.usuarios (telefono, origen, fecha_registro)
                SELECT :phone, :origen, CURRENT_TIMESTAMP
                WHERE NOT EXISTS (
                    SELECT 1 FROM hatsu.usuarios 
                    WHERE telefono = :phone AND origen = :origen
                )
                RETURNING id
            )
            SELECT id FROM new_user
            UNION ALL
            SELECT id FROM hatsu.usuarios 
            WHERE telefono = :phone AND origen = :origen
            LIMIT 1
        """)
        result = await session.execute(user_query, {"phone": from_number, "origen": "whatsapp"})
        usuario_id = result.scalar_one()
        await session.commit()

        # Obtener o crear el agente para este usuario
        current_time = time.time()
        if usuario_id not in user_agents:
            agent = TestAIAgent(menu_data=menu_data, locales_data=locales_data)
            await agent.initialize_user_data(session, from_number, "whatsapp")
            user_agents[usuario_id] = (agent, current_time)
            logger.info(f"Nuevo agente creado para usuario {usuario_id}")
        else:
            agent, _ = user_agents[usuario_id]
            user_agents[usuario_id] = (agent, current_time)  # Actualizar timestamp
            logger.info(f"Usando agente existente para usuario {usuario_id}")

        is_human_request = body.lower() in ["#human", "hablar con humano", "operador", "ayuda humana"] or "hablar con" in body.lower()

        mensaje_id = await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=body,
            rol="usuario",
            canal="whatsapp",
            intervencion_humana=is_human_request,
            media_url=media_url
        )
        await session.commit()

        logger.info(f"Mensaje guardado con ID: {mensaje_id}")

        if is_human_request:
            await mark_conversation_for_human(session, usuario_id, canal="whatsapp")
            await cleanup_inactive_agents()  # Limpiar agentes inactivos
            return {"status": "success", "message": "Intervención humana activada"}

        is_human_mode = await is_in_human_mode(session, usuario_id)
        if is_human_mode:
            await cleanup_inactive_agents()  # Limpiar agentes inactivos
            return {"status": "success", "message": "Modo humano activo"}

        try:
            logger.info("=== INICIANDO PROCESAMIENTO DE MENSAJE ===")
            logger.info(f"Mensaje a procesar: {body}")
            
            # Si hay imagen, incluirla en el procesamiento
            if media_url:
                full_response = await agent.process_message(
                    message=body,
                    session=session,
                    phone=from_number.replace("whatsapp:", ""),
                    origen="whatsapp",
                    media_url=media_url
                )
            else:
                full_response = await agent.process_message(
                    message=body,
                    session=session,
                    phone=from_number.replace("whatsapp:", ""),
                    origen="whatsapp"
                )
            logger.info(f"Respuesta completa del agente: {full_response}")

            user_message = full_response
            if "#ORDER:" in full_response:
                logger.info("=== PROCESANDO ORDEN ===")
                parts = full_response.split("#ORDER:")
                user_message = parts[0].strip()
                order_data = parts[1].strip()
                
                # Asegurarnos de obtener solo el JSON válido
                if "}" in order_data:
                    order_json = order_data[:order_data.rindex("}") + 1]
                    logger.info(f"JSON de la orden limpio: {order_json}")
                    order_success, is_new_user, confirmation_message = await process_order(f"#ORDER:{order_json}", session, from_number)
                    logger.info(f"Resultado del procesamiento: success={order_success}, is_new_user={is_new_user}")
                    logger.info(f"Mensaje de confirmación: {confirmation_message}")
                    user_message = confirmation_message if order_success else "Lo siento, hubo un problema al procesar tu orden."
                else:
                    logger.error("JSON de orden inválido - no se encontró el cierre '}'")
                    user_message = "Lo siento, hubo un problema al procesar tu orden."

            if "#USER_DATA:" in full_response:
                logger.info("=== PROCESANDO DATOS DE USUARIO ===")
                parts = full_response.split("#USER_DATA:")
                user_message = parts[0].strip()
                user_data = parts[1].strip()
                logger.info(f"Datos de usuario a actualizar: {user_data}")
                if await update_user_data(f"#USER_DATA:{user_data}", session, from_number, "whatsapp"):
                    await agent.initialize_user_data(session, from_number, "whatsapp")
                    logger.info("Datos de usuario actualizados correctamente")

            logger.info("=== GUARDANDO MENSAJE DE RESPUESTA ===")
            await save_message(
                session=session,
                usuario_id=usuario_id,
                mensaje=user_message,
                rol="agente",
                canal="whatsapp",
                media_url=None
            )
            await session.commit()

            logger.info("=== ENVIANDO RESPUESTA A WHATSAPP ===")
            await send_whatsapp_message_cloud(from_number, user_message)

            # Limpiar agentes inactivos después de procesar el mensaje
            await cleanup_inactive_agents()

            return {"status": "success", "response": user_message}

        except Exception as e:
            logger.error(f"Error procesando mensaje del agente: {str(e)}")
            error_message = "Lo siento, hubo un problema al procesar tu mensaje."
            await save_message(
                session=session,
                usuario_id=usuario_id,
                mensaje=error_message,
                rol="agente",
                canal="whatsapp",
                media_url=None
            )
            await session.commit()
            await send_whatsapp_message_cloud(from_number, error_message)
            await cleanup_inactive_agents()  # Limpiar agentes inactivos incluso en caso de error
            return {"status": "error", "message": str(e)}

    except Exception as e:
        logger.error(f"Error procesando webhook: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "agent": "initialized" if menu_data and locales_data else "not_initialized",
        "database_url": os.getenv("DATABASE_URL", "not_set"),
        "active_agents": len(user_agents)
    }

if __name__ == "__main__":
    logger.info("Iniciando servidor WhatsApp Cloud API...")
    uvicorn.run(
        "app.api.whatsapp_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )