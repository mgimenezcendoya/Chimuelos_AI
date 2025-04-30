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

# Agregar el directorio raíz al path para poder importar desde app
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from app.services.test_agent import TestAIAgent
from app.database.database import async_session, init_db, Orden, OrdenDetalle
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy import text as sql_text
from decimal import Decimal

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

async def get_menu_from_db(session: AsyncSession):
    """Obtiene el menú desde la base de datos"""
    try:
        # Consultar todos los productos activos
        logger.info("Consultando productos activos...")
        query = text("""
            SELECT nombre, descripcion, precio_base, es_combo
            FROM hatsu.productos
            WHERE activo = true
            ORDER BY es_combo, nombre
        """)
        result = await session.execute(query)
        productos = result.fetchall()
        logger.info(f"Productos encontrados: {len(productos)}")
        
        # Estructurar el menú
        menu = {
            "rolls_clasicos": {
                "title": "ROLLS CLÁSICOS",
                "description": "8 piezas",
                "items": []
            },
            "rolls_especiales": {
                "title": "ROLLS ESPECIALES",
                "description": "8 piezas",
                "items": []
            },
            "combos": {
                "title": "COMBOS",
                "items": []
            }
        }
        
        # Clasificar productos
        logger.info("Clasificando productos...")
        for producto in productos:
            item = {
                "name": producto.nombre,
                "price": int(producto.precio_base),
                "description": producto.descripcion
            }
            
            if producto.es_combo:
                menu["combos"]["items"].append(item)
            elif "especial" in producto.nombre.lower():
                menu["rolls_especiales"]["items"].append(item)
            else:
                menu["rolls_clasicos"]["items"].append(item)
        
        logger.info(f"Menú estructurado: {len(menu['rolls_clasicos']['items'])} rolls clásicos, {len(menu['rolls_especiales']['items'])} rolls especiales, {len(menu['combos']['items'])} combos")
        return menu
    except Exception as e:
        logger.error(f"Error obteniendo menú de la base de datos: {str(e)}")
        return None

async def get_locales_from_db(session: AsyncSession):
    """Obtiene los locales desde la base de datos"""
    try:
        query = text("""
            SELECT nombre, direccion, telefono
            FROM hatsu.locales
            WHERE activo = true
            ORDER BY nombre
        """)
        result = await session.execute(query)
        locales = result.fetchall()
        
        # Estructurar la información de locales
        locales_info = {
            "title": "NUESTROS LOCALES",
            "locations": []
        }
        
        for local in locales:
            locales_info["locations"].append({
                "name": local.nombre,
                "address": local.direccion,
                "phone": local.telefono
            })
        
        return locales_info
    except Exception as e:
        logger.error(f"Error obteniendo locales de la base de datos: {str(e)}")
        return None

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

def _format_order_confirmation(order_data: dict, user_address: str = None) -> str:
    """Formatea el mensaje de confirmación de orden con emojis y detalles"""
    items = []
    total = 0
    
    # Formatear cada item con su subtotal
    for item in order_data.get("items", []):
        product = item["product"]
        quantity = item["quantity"]
        precio_unitario = int(float(str(item["precio_unitario"])))
        subtotal = int(float(str(item["subtotal"])))
        total += subtotal
        
        # Formatear el subtotal con separadores de miles
        subtotal_formatted = f"${subtotal:,}".replace(",", ".")
        items.append(f"{quantity}x {product} - {subtotal_formatted}")
    
    # Construir el mensaje
    message = ["¡Pedido confirmado! 🎉\n"]
    message.append("\n📝 Detalles del pedido:")
    message.extend(items)
    
    # Formatear el total con separadores de miles
    total_formatted = f"${total:,}".replace(",", ".")
    message.append(f"💰 Total: {total_formatted}")
    
    # Agregar modo de entrega
    delivery_mode = "Delivery" if not order_data.get("is_takeaway", False) else "Retiro en local"
    message.append(f"\n🚗 Modo de entrega: {delivery_mode}")
    
    # Agregar dirección si es delivery
    if not order_data.get("is_takeaway", False) and user_address:
        message.append(f"\n🏠 Dirección de entrega: {user_address}")
    
    # Agregar medio de pago
    payment_method = order_data.get("medio_pago", "pendiente")
    payment_emoji = "💵" if payment_method == "efectivo" else "💳" if payment_method == "mercadopago" else "❓"
    message.append(f"\n{payment_emoji} Medio de pago: {payment_method.capitalize()}")
    
    return "\n".join(message)

async def process_order(message_text: str, session: AsyncSession, phone: str):
    """Procesa una orden y la guarda en la base de datos"""
    try:
        # Buscar el formato #ORDER:{} en el texto
        if "#ORDER:" in message_text:
            order_json = message_text.split("#ORDER:")[1].strip()
            order_data = json.loads(order_json)
            
            # Determinar la fuente del pedido
            source = "whatsapp" if phone.startswith("whatsapp:") else "console"
            clean_phone = phone.replace("whatsapp:", "")
            
            # Verificar si ya existe una orden con el mismo contenido en los últimos 5 minutos
            check_duplicate_query = sql_text("""
                SELECT o.id 
                FROM hatsu.ordenes o
                JOIN hatsu.usuarios u ON o.usuario_id = u.id
                WHERE u.telefono = :phone
                AND u.source = :source
                AND o.fecha_hora > NOW() - INTERVAL '5 minutes'
                AND o.monto_total = :monto_total
                LIMIT 1
            """)
            
            result = await session.execute(
                check_duplicate_query,
                {
                    "phone": clean_phone,
                    "source": source,
                    "monto_total": int(float(str(order_data["total"])))
                }
            )
            
            if result.scalar_one_or_none() is not None:
                logger.warning(f"Orden duplicada detectada para {phone} desde {source}")
                return False, False, None
            
            # Obtener o crear usuario
            user_query = sql_text("""
                WITH new_user AS (
                    INSERT INTO hatsu.usuarios (telefono, source, fecha_registro)
                    SELECT :phone, :source, CURRENT_TIMESTAMP
                    WHERE NOT EXISTS (
                        SELECT 1 FROM hatsu.usuarios 
                        WHERE telefono = :phone AND source = :source
                    )
                    RETURNING id, true as is_new
                )
                SELECT id, false as is_new FROM hatsu.usuarios 
                WHERE telefono = :phone AND source = :source
                UNION ALL
                SELECT id, is_new FROM new_user
                LIMIT 1
            """)
            
            result = await session.execute(
                user_query,
                {
                    "phone": clean_phone,
                    "source": source
                }
            )
            row = result.fetchone()
            usuario_id = row[0]
            is_new_user = row[1]
            
            # Obtener nombre y dirección del usuario si existe
            user_address = None
            if not is_new_user:
                user_data_query = sql_text("""
                    SELECT nombre, direccion FROM hatsu.usuarios WHERE id = :usuario_id
                """)
                result = await session.execute(user_data_query, {"usuario_id": usuario_id})
                user_data = result.fetchone()
                if user_data:
                    user_address = user_data[1]
            
            # Obtener el local de Vicente Lopez
            local_query = sql_text("""
                SELECT id FROM hatsu.locales 
                WHERE nombre = 'Vicente Lopez'
                AND activo = true 
                LIMIT 1
            """)
            result = await session.execute(local_query)
            local_id = result.scalar_one()
            
            if not local_id:
                logger.error("Local de Vicente Lopez no encontrado o no activo")
                return False, False, None
            
            # Insertar la orden
            order_query = sql_text("""
                INSERT INTO hatsu.ordenes (
                    usuario_id, local_id, fecha_hora, estado, monto_total, medio_pago, is_takeaway
                ) VALUES (
                    :usuario_id, :local_id, CURRENT_TIMESTAMP, 'pendiente', :monto_total, :medio_pago, :is_takeaway
                )
                RETURNING id
            """)
            
            # Calcular el monto_total sumando los subtotales de los detalles
            monto_total = 0
            for item in order_data.get("items", []):
                subtotal = int(float(str(item["subtotal"])))
                monto_total += subtotal

            result = await session.execute(
                order_query,
                {
                    "usuario_id": usuario_id,
                    "local_id": local_id,
                    "monto_total": monto_total,
                    "is_takeaway": order_data.get("is_takeaway", False),
                    "medio_pago": order_data.get("medio_pago", "pendiente")
                }
            )
            orden_id = result.scalar_one()

            # Insertar los detalles de la orden
            for item in order_data.get("items", []):
                # Buscar el ID del producto por su nombre
                product_query = sql_text("""
                    SELECT id FROM hatsu.productos 
                    WHERE nombre = :nombre AND activo = true
                    LIMIT 1
                """)
                result = await session.execute(product_query, {"nombre": item["product"]})
                producto_id = result.scalar_one()
                
                detail_query = sql_text("""
                    INSERT INTO hatsu.orden_detalle (
                        orden_id, producto_id, cantidad, precio_unitario, subtotal
                    ) VALUES (
                        :orden_id, :producto_id, :cantidad, :precio_unitario, :subtotal
                    )
                """)
                
                # Usar los valores directamente del item
                cantidad = int(float(str(item["quantity"])))
                precio_unitario = int(float(str(item["precio_unitario"])))
                subtotal = int(float(str(item["subtotal"])))
                
                await session.execute(
                    detail_query,
                    {
                        "orden_id": orden_id,
                        "producto_id": producto_id,
                        "cantidad": cantidad,
                        "precio_unitario": precio_unitario,
                        "subtotal": subtotal
                    }
                )
            
            await session.commit()
            logger.info(f"Nueva orden {orden_id} guardada para {phone} desde {source}")
            
            # Generar mensaje de confirmación formateado
            confirmation_message = _format_order_confirmation(order_data, user_address)
            return True, is_new_user, confirmation_message
            
    except Exception as e:
        logger.error(f"Error procesando orden: {str(e)}")
        await session.rollback()
        return False, False, None

async def update_user_data(text: str, session: AsyncSession, phone: str):
    """Actualiza los datos del usuario"""
    try:
        if "#USER_DATA:" in text:
            user_data_json = text.split("#USER_DATA:")[1].strip()
            user_data = json.loads(user_data_json)
            
            # Limpiar el número de teléfono si viene de WhatsApp
            clean_phone = phone.replace("whatsapp:", "")
            source = "whatsapp" if phone.startswith("whatsapp:") else "console"
            
            update_query = sql_text("""
                UPDATE hatsu.usuarios
                SET nombre = :nombre,
                    email = :email,
                    direccion = :direccion
                WHERE telefono = :phone AND source = :source
                RETURNING id
            """)
            
            result = await session.execute(
                update_query,
                {
                    "nombre": user_data.get("nombre"),
                    "email": user_data.get("email"),
                    "direccion": user_data.get("direccion"),
                    "phone": clean_phone,
                    "source": source
                }
            )
            
            await session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Error actualizando datos de usuario: {str(e)}")
        await session.rollback()
        return False

async def get_user_data(session: AsyncSession, phone: str):
    """Obtiene los datos del usuario si existe"""
    try:
        # Limpiar el número de teléfono si viene de WhatsApp
        clean_phone = phone.replace("whatsapp:", "")
        source = "whatsapp" if phone.startswith("whatsapp:") else "console"
        
        query = sql_text("""
            SELECT nombre, direccion FROM hatsu.usuarios
            WHERE telefono = :phone 
            AND source = :source 
            AND (nombre IS NOT NULL OR direccion IS NOT NULL)
        """)
        result = await session.execute(query, {"phone": clean_phone, "source": source})
        row = result.first()
        if row:
            return {
                "nombre": row[0],
                "direccion": row[1]
            }
        return None
    except Exception as e:
        logger.error(f"Error obteniendo datos de usuario: {str(e)}")
        return None

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
    Body: str = Form(...),
    From: str = Form(...),
    session: AsyncSession = Depends(get_db)
):
    """
    Maneja los webhooks entrantes de WhatsApp
    """
    try:
        logger.info(f"Mensaje recibido de {From}: {Body}")
        
        # Solo procesar si es un mensaje de WhatsApp
        if not From.startswith('whatsapp:'):
            logger.info(f"Ignorando mensaje no-WhatsApp de {From}")
            return {"status": "ignored", "message": "Not a WhatsApp message"}
        
        # Si es un mensaje de unión al sandbox, responder apropiadamente
        if Body.lower().startswith('join'):
            # Verificar si es un usuario existente y obtener sus datos
            user_data = await get_user_data(session, From)
            welcome_msg = "¡Bienvenido a Hatsu Sushi - Vicente Lopez!"
            
            # Establecer los datos del usuario en el agente
            if user_data:
                ai_agent.set_user_data(
                    name=user_data.get("nombre"),
                    address=user_data.get("direccion")
                )
                if user_data.get("nombre"):
                    welcome_msg = f"¡Hola {user_data.get('nombre')}! ¡Bienvenido nuevamente a Hatsu Sushi - Vicente Lopez!"
            else:
                ai_agent.set_user_data(name=None, address=None)
            
            welcome_msg += " Estoy aquí para ayudarte con tu pedido. ¿Qué te gustaría ordenar?"
            
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
        
        # Procesar el mensaje con el agente
        try:
            # Verificar si el usuario tiene datos registrados y establecerlos en el agente
            user_data = await get_user_data(session, From)
            if user_data:
                # Establecer los datos del usuario en el agente antes de procesar el mensaje
                ai_agent.set_user_data(
                    name=user_data.get("nombre"),
                    address=user_data.get("direccion")
                )
            else:
                # Si no hay datos del usuario, asegurarse de que el agente no tenga datos antiguos
                ai_agent.set_user_data(name=None, address=None)

            full_response = await ai_agent.process_message(Body)
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
                    updated_user_data = await get_user_data(session, From)
                    if updated_user_data:
                        ai_agent.set_user_data(
                            name=updated_user_data.get("nombre"),
                            address=updated_user_data.get("direccion")
                        )
            
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