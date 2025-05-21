import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends
from dotenv import load_dotenv
from twilio.rest import Client
import asyncio
import uvicorn
import json
from datetime import datetime
import sys
from pathlib import Path
from sqlalchemy.sql import text as sql_text
import time

# Agregar el directorio raíz al path para poder importar desde app
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

# Cargar variables de entorno
load_dotenv()

# Get schema name from environment variable
SCHEMA_NAME = os.getenv("SCHEMA_NAME", "hatsu")

from app.services.test_agent import TestAIAgent
from app.database.database import async_session, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.db_utils import (
    get_menu_from_db, get_locales_from_db, process_order,
    update_user_data, get_user_data, _format_order_confirmation,
    save_message, mark_conversation_for_human, is_in_human_mode,
    get_user_session_message_count
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


logger.info("Variables de entorno cargadas")

# Configuración de Twilio
SANDBOX_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')  # Número fijo del sandbox
twilio_client = Client(
    os.getenv('TWILIO_ACCOUNT_SID'),
    os.getenv('TWILIO_AUTH_TOKEN')
)
logger.info("Cliente Twilio inicializado")

# Diccionario para almacenar los agentes por usuario y su última actividad
user_agents = {}  # {usuario_id: (TestAIAgent, last_seen_timestamp)}

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

# Instanciar el agente
menu_data = None
locales_data = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manejador de eventos de lifespan de la aplicación"""
    # Inicialización
    await init_db()
    logger.info("Base de datos inicializada")
    
    # Obtener menú y locales
    async with async_session() as session:
        global menu_data, locales_data
        menu_data = await get_menu_from_db(session)
        locales_data = await get_locales_from_db(session)
        
        if not menu_data:
            logger.warning("No se pudo obtener el menú de la base de datos")
    
    yield
    # Limpieza al cerrar
    logger.info("Cerrando aplicación...")

app = FastAPI(lifespan=lifespan)

# Función para obtener una sesión de base de datos
async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

@app.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(None),  # Hacemos Body opcional
    From: str = Form(None),  # Hacemos From opcional
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
    NumMedia: str = Form("0"),
    session: AsyncSession = Depends(get_db)
):
    """
    Maneja los webhooks entrantes de WhatsApp
    """
    try:
        # Log de todos los datos recibidos
        form_data = await request.form()
        logger.info(f"Datos completos recibidos en webhook: {dict(form_data)}")
        
        # Validación básica
        if not Body and not MediaUrl0:
            return {"status": "error", "message": "Se requiere Body o MediaUrl0"}
        
        if not From:
            return {"status": "error", "message": "Se requiere From"}
            
        logger.info(f"Mensaje recibido de {From}: {Body}")
        if MediaUrl0:
            logger.info(f"Imagen recibida: {MediaUrl0}")
        
        # Solo procesar si es un mensaje de WhatsApp
        if not From.startswith('whatsapp:'):
            logger.info(f"Ignorando mensaje no-WhatsApp de {From}")
            return {"status": "ignored", "message": "Not a WhatsApp message"}
        
        # Obtener o crear usuario
        phone_number = From.replace("whatsapp:", "")  # Extraer solo el número
        user_query = sql_text(f"""
            WITH new_user AS (
                INSERT INTO {SCHEMA_NAME}.usuarios (telefono, origen, fecha_registro)
                SELECT :phone, :origen, CURRENT_TIMESTAMP
                WHERE NOT EXISTS (
                    SELECT 1 FROM {SCHEMA_NAME}.usuarios 
                    WHERE telefono = :phone AND origen = :origen
                )
                RETURNING id
            )
            SELECT id FROM new_user
            UNION ALL
            SELECT id FROM {SCHEMA_NAME}.usuarios 
            WHERE telefono = :phone AND origen = :origen
            LIMIT 1
        """)
        result = await session.execute(
            user_query,
            {
                "phone": phone_number,
                "origen": "whatsapp"
            }
        )
        usuario_id = result.scalar_one()
        await session.commit()
        
        # Obtener o crear el agente para este usuario
        current_time = time.time()
        if usuario_id not in user_agents:
            if not menu_data or not locales_data:
                logger.error("No se puede crear el agente: menú o locales no disponibles")
                return {"status": "error", "message": "Servicio no disponible temporalmente"}
                
            agent = TestAIAgent(menu_data=menu_data, locales_data=locales_data)
            await agent.initialize_user_data(session, From.replace("whatsapp:", ""), "whatsapp")
            user_agents[usuario_id] = (agent, current_time)
            logger.info(f"Nuevo agente creado para usuario {usuario_id}")
        else:
            agent, _ = user_agents[usuario_id]
            user_agents[usuario_id] = (agent, current_time)  # Actualizar timestamp
            logger.info(f"Usando agente existente para usuario {usuario_id}")
        
        # Si es un mensaje de unión al sandbox, responder apropiadamente
        if Body and Body.lower().startswith('join'):
            welcome_msg = "¡Bienvenido a Hatsu Sushi - Vicente Lopez!"
            if agent.user_name:
                welcome_msg = f"¡Hola {agent.user_name}! ¡Bienvenido nuevamente a Hatsu Sushi - Vicente Lopez!"
            welcome_msg += " Estoy aquí para ayudarte con tu pedido. ¿Qué te gustaría ordenar?"
            
            # Contar tokens del mensaje de bienvenida
            welcome_tokens = agent.estimate_prompt_tokens(welcome_msg)
            
            # Guardar mensaje de bienvenida
            await save_message(
                session=session,
                usuario_id=usuario_id,
                mensaje=welcome_msg,
                rol="agente",
                canal="whatsapp",
                media_url=None,
                tokens=welcome_tokens
            )
            await session.commit()
            
            try:
                message = twilio_client.messages.create(
                    from_=SANDBOX_NUMBER,
                    body=welcome_msg,
                    to=From
                )
                logger.info(f"Mensaje de bienvenida enviado con SID: {message.sid}")
                await cleanup_inactive_agents()  # Limpiar agentes inactivos
            except Exception as e:
                logger.error(f"Error enviando mensaje de bienvenida: {str(e)}")
            return {"status": "success", "message": welcome_msg}
        
        # Verificar si el usuario está solicitando intervención humana
        is_human_request = False
        if Body:  # Solo verificar si hay texto
            is_human_request = Body.lower() in ["#human", "hablar con humano", "operador", "ayuda humana"] or "hablar con" in Body.lower()
        
        # Si solo hay imagen sin texto, usar un mensaje descriptivo
        mensaje_a_guardar = Body if Body else "[Imagen enviada sin texto]"
        
        # Contar tokens del mensaje del usuario
        prompt_tokens = agent.estimate_prompt_tokens(mensaje_a_guardar)
        
        # Guardar mensaje del usuario con intervencion_humana si corresponde
        mensaje_id = await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=mensaje_a_guardar,
            rol="usuario",
            canal="whatsapp",
            intervencion_humana=is_human_request,
            media_url=MediaUrl0,
            tokens=prompt_tokens
        )
        await session.commit()
        
        # Limitar mensajes por sesión (después de guardar el mensaje)
        count, _ = await get_user_session_message_count(session, usuario_id)
        if count > 100:
            limite_msg = "Has excedido el límite de mensajes para esta sesión. Por favor, espera o inicia una nueva sesión más tarde."
            output_tokens = max(1, len(limite_msg) // 4)
            await save_message(
                session=session,
                usuario_id=usuario_id,
                mensaje=limite_msg,
                rol="agente",
                canal="whatsapp",
                media_url=None,
                tokens=output_tokens
            )
            await session.commit()
            try:
                message = twilio_client.messages.create(
                    from_=SANDBOX_NUMBER,
                    body=limite_msg,
                    to=From
                )
                logger.info(f"Mensaje de límite enviado con SID: {message.sid}")
            except Exception as e:
                logger.error(f"Error enviando mensaje de límite: {str(e)}")
            await cleanup_inactive_agents()
            return {"status": "success", "message": limite_msg}
        
        # Log para verificar que el mensaje se guardó correctamente
        logger.info(f"Mensaje guardado con ID: {mensaje_id}, media_url: {MediaUrl0}")
        
        if is_human_request:
            # Activar intervención humana y retornar el mensaje de transición
            await mark_conversation_for_human(session, usuario_id, canal="whatsapp")
            human_msg = "Perfecto, en breve una persona de nuestro local continúa esta conversación."
            
            # Contar tokens del mensaje de transición
            human_tokens = max(1, len(human_msg) // 4)
            
            # Guardar mensaje de transición
            await save_message(
                session=session,
                usuario_id=usuario_id,
                mensaje=human_msg,
                rol="agente",
                canal="whatsapp",
                intervencion_humana=True,
                tokens=human_tokens
            )
            await session.commit()
            
            try:
                message = twilio_client.messages.create(
                    from_=SANDBOX_NUMBER,
                    body=human_msg,
                    to=From
                )
                logger.info(f"Mensaje de transición enviado con SID: {message.sid}")
            except Exception as e:
                logger.error(f"Error enviando mensaje de transición: {str(e)}")
            
            await cleanup_inactive_agents()  # Limpiar agentes inactivos
            return {"status": "success", "message": human_msg}
        
        # Verificar si está en modo humano antes de procesar con el agente
        is_human_mode = await is_in_human_mode(session, usuario_id)
        if is_human_mode:
            # Si está en modo humano, solo guardamos el mensaje del usuario y no enviamos respuesta
            await cleanup_inactive_agents()  # Limpiar agentes inactivos
            return {"status": "success", "message": "Message saved in human mode"}
        
        # Solo procesar con el agente si NO está en modo humano
        if not is_human_mode:
            try:
                # Si hay una imagen, procesar con el agente incluyendo la URL
                if MediaUrl0:
                    full_response = await agent.process_message(mensaje_a_guardar, media_url=MediaUrl0)
                else:
                    full_response = await agent.process_message(mensaje_a_guardar)
                logger.info(f"Respuesta completa del agente: {full_response}")

                orden_id = None
                orden_creada = False
                
                # Separar el mensaje para el usuario del JSON técnico
                user_message = full_response
                if "#ORDER:" in full_response:
                    parts = full_response.split("#ORDER:")
                    user_message = parts[0].strip()
                    order_json = parts[1].strip()
                    if "}" in order_json:
                        order_json = order_json[:order_json.rindex("}") + 1]
                    
                    # Parsear el JSON de la orden para asegurar que tiene todos los campos requeridos
                    order_data = json.loads(order_json)
                    
                    # Registrar el procesamiento de la orden
                    logger.info(f"Procesando orden de WhatsApp para {From}")
                    
                    # Procesar la orden
                    success, is_new_user, confirmation_message, orden_id = await process_order(
                        text=f"#ORDER:{order_json}",
                        session=session,
                        phone=From.replace("whatsapp:", ""),
                        origen="whatsapp"
                    )
                    if success:
                        orden_creada = True 
                        user_message = confirmation_message
                    else:
                        user_message += "\n\nLo siento, hubo un problema al procesar tu orden. Por favor, intenta nuevamente."
                
                if "#USER_DATA:" in full_response:
                    parts = full_response.split("#USER_DATA:")
                    user_message = parts[0].strip()
                    # Extract the user data JSON and clean it up
                    user_data = parts[1].strip()
                    # Remove any trailing text after the JSON object
                    if "}" in user_data:
                        user_data = user_data[:user_data.rindex("}") + 1]
                    # Actualizar datos del usuario
                    if await update_user_data(f"#USER_DATA:{user_data}", session, From):
                        # Recargar los datos del usuario en el agente
                        await agent.initialize_user_data(session, From.replace("whatsapp:", ""), "whatsapp")
                
                # Contar tokens de la respuesta
                output_tokens = max(1, len(user_message) // 4)
                
                # Guardar respuesta del agente
                await save_message(
                    session=session,
                    usuario_id=usuario_id,
                    mensaje=user_message,
                    rol="agente",
                    canal="whatsapp",
                    orden_id=orden_id,
                    orden_creada=orden_creada,
                    media_url=None,
                    tokens=output_tokens
                )
                await session.commit()
                
                # Intentar enviar respuesta por WhatsApp
                try:
                    message = twilio_client.messages.create(
                        from_=SANDBOX_NUMBER,
                        body=user_message,
                        to=From
                    )
                    logger.info(f"Mensaje enviado con SID: {message.sid}")
                except Exception as e:
                    logger.error(f"Error enviando mensaje por WhatsApp: {str(e)}")
                
                await cleanup_inactive_agents()  # Limpiar agentes inactivos
                return {
                    "status": "success", 
                    "response": user_message,
                    "note": "El mensaje puede no haberse enviado por WhatsApp debido a límites de la cuenta"
                }
            except Exception as e:
                logger.error(f"Error procesando mensaje del agente: {str(e)}")
                error_message = "Lo siento, hubo un problema al procesar tu mensaje. Por favor, intenta nuevamente."
                
                # Contar tokens del mensaje de error
                error_tokens = max(1, len(error_message) // 4)
                
                # Guardar mensaje de error
                await save_message(
                    session=session,
                    usuario_id=usuario_id,
                    mensaje=error_message,
                    rol="agente",
                    canal="whatsapp",
                    media_url=None,
                    tokens=error_tokens
                )
                await session.commit()
                
                message = twilio_client.messages.create(
                    from_=SANDBOX_NUMBER,
                    body=error_message,
                    to=From
                )
                await cleanup_inactive_agents()  # Limpiar agentes inactivos
                return {"status": "error", "message": str(e)}
    
    except Exception as e:
        logger.error(f"Error procesando mensaje: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """
    Endpoint para verificar que el servidor está funcionando
    """
    return {
        "status": "healthy",
        "menu_data": "initialized" if menu_data else "not_initialized",
        "locales_data": "initialized" if locales_data else "not_initialized",
        "database_url": os.getenv("DATABASE_URL", "not_set"),
        "twilio_sandbox": SANDBOX_NUMBER,
        "active_agents": len(user_agents)
    }

if __name__ == "__main__":
    # Ejecutar el servidor
    logger.info("Iniciando servidor WhatsApp...")
    uvicorn.run(
        "app.api.whatsapp_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    ) 