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

# Configuración de Twilio
SANDBOX_NUMBER = 'whatsapp:+14155238886'  # Número fijo del sandbox
twilio_client = Client(
    os.getenv('TWILIO_ACCOUNT_SID'),
    os.getenv('TWILIO_AUTH_TOKEN')
)
logger.info("Cliente Twilio inicializado")

# Instanciar el agente
ai_agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manejador de eventos de lifespan de la aplicación"""
    # Inicialización
    await init_db()
    logger.info("Base de datos inicializada")
    
    # Obtener menú y locales, y crear agente
    async with async_session() as session:
        menu = await get_menu_from_db(session)
        locales = await get_locales_from_db(session)
        
        if menu:
            global ai_agent
            ai_agent = TestAIAgent(menu_data=menu, locales_data=locales)
            logger.info("Agente AI inicializado con menú y locales de la base de datos")
        else:
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
        result = await session.execute(
            user_query,
            {
                "phone": From.replace("whatsapp:", ""),
                "origen": "whatsapp"
            }
        )
        usuario_id = result.scalar_one()
        await session.commit()
        
        # Inicializar datos del usuario en el agente
        await ai_agent.initialize_user_data(session, From.replace("whatsapp:", ""), "whatsapp")
        
        # Si es un mensaje de unión al sandbox, responder apropiadamente
        if Body and Body.lower().startswith('join'):
            welcome_msg = "¡Bienvenido a Hatsu Sushi - Vicente Lopez!"
            if ai_agent.user_name:
                welcome_msg = f"¡Hola {ai_agent.user_name}! ¡Bienvenido nuevamente a Hatsu Sushi - Vicente Lopez!"
            welcome_msg += " Estoy aquí para ayudarte con tu pedido. ¿Qué te gustaría ordenar?"
            
            # Guardar mensaje de bienvenida
            await save_message(
                session=session,
                usuario_id=usuario_id,
                mensaje=welcome_msg,
                rol="agente",
                canal="whatsapp",
                media_url=None
            )
            await session.commit()
            
            try:
                message = twilio_client.messages.create(
                    from_=SANDBOX_NUMBER,
                    body=welcome_msg,
                    to=From
                )
                logger.info(f"Mensaje de bienvenida enviado con SID: {message.sid}")
            except Exception as e:
                logger.error(f"Error enviando mensaje de bienvenida: {str(e)}")
            return {"status": "success", "message": welcome_msg}
        
        # Verificar si el usuario está solicitando intervención humana
        is_human_request = False
        if Body:  # Solo verificar si hay texto
            is_human_request = Body.lower() in ["#human", "hablar con humano", "operador", "ayuda humana"] or "hablar con" in Body.lower()
        
        # Si solo hay imagen sin texto, usar un mensaje descriptivo
        mensaje_a_guardar = Body if Body else "[Imagen enviada sin texto]"
        
        # Guardar mensaje del usuario con intervencion_humana si corresponde
        mensaje_id = await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=mensaje_a_guardar,
            rol="usuario",
            canal="whatsapp",
            intervencion_humana=is_human_request,
            media_url=MediaUrl0
        )
        await session.commit()
        
        # Log para verificar que el mensaje se guardó correctamente
        logger.info(f"Mensaje guardado con ID: {mensaje_id}, media_url: {MediaUrl0}")
        
        if is_human_request:
            # Activar intervención humana y retornar el mensaje de transición
            await mark_conversation_for_human(session, usuario_id, canal="whatsapp")
            return {"status": "success", "message": "Intervención humana activada"}
        
        # Verificar si está en modo humano antes de procesar con el agente
        is_human_mode = await is_in_human_mode(session, usuario_id)
        if is_human_mode:
            # Si está en modo humano, solo guardamos el mensaje del usuario y no enviamos respuesta
            return {"status": "success", "message": "Message saved in human mode"}
        
        # Solo procesar con el agente si NO está en modo humano
        if not is_human_mode:
            try:
                # Si hay una imagen, procesar con el agente incluyendo la URL
                if MediaUrl0:
                    full_response = await ai_agent.process_message(mensaje_a_guardar, media_url=MediaUrl0)
                else:
                    full_response = await ai_agent.process_message(mensaje_a_guardar)
                logger.info(f"Respuesta completa del agente: {full_response}")
                
                # Separar el mensaje para el usuario del JSON técnico
                user_message = full_response
                if "#ORDER:" in full_response:
                    parts = full_response.split("#ORDER:")
                    user_message = parts[0].strip()
                    order_data = parts[1].strip()
                    # Procesar la orden
                    logger.info(f"Procesando orden de WhatsApp para {From}")
                    order_success, is_new_user, confirmation_message = await process_order(f"#ORDER:{order_data}", session, From)
                    if order_success:
                        user_message = confirmation_message
                    else:
                        user_message += "\n\nLo siento, hubo un problema al procesar tu orden. Por favor, intenta nuevamente."
                
                if "#USER_DATA:" in full_response:
                    parts = full_response.split("#USER_DATA:")
                    user_message = parts[0].strip()
                    user_data = parts[1].strip()
                    # Actualizar datos del usuario
                    if await update_user_data(f"#USER_DATA:{user_data}", session, From):
                        # Recargar los datos del usuario en el agente
                        await ai_agent.initialize_user_data(session, From.replace("whatsapp:", ""), "whatsapp")
                
                # Guardar respuesta del agente
                await save_message(
                    session=session,
                    usuario_id=usuario_id,
                    mensaje=user_message,
                    rol="agente",
                    canal="whatsapp",
                    media_url=None
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
                
                return {
                    "status": "success", 
                    "response": user_message,
                    "note": "El mensaje puede no haberse enviado por WhatsApp debido a límites de la cuenta"
                }
            except Exception as e:
                logger.error(f"Error procesando mensaje del agente: {str(e)}")
                error_message = "Lo siento, hubo un problema al procesar tu mensaje. Por favor, intenta nuevamente."
                
                # Guardar mensaje de error
                await save_message(
                    session=session,
                    usuario_id=usuario_id,
                    mensaje=error_message,
                    rol="agente",
                    canal="whatsapp",
                    media_url=None
                )
                await session.commit()
                
                message = twilio_client.messages.create(
                    from_=SANDBOX_NUMBER,
                    body=error_message,
                    to=From
                )
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
        "agent": "initialized" if ai_agent else "not_initialized",
        "database_url": os.getenv("DATABASE_URL", "not_set"),
        "twilio_sandbox": SANDBOX_NUMBER
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