import os
import logging
import asyncio
import json
from datetime import datetime
import sys
from pathlib import Path

# Agregar el directorio raíz al path para poder importar desde app
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from app.services.test_agent import TestAIAgent
from app.database.database import async_session, Orden, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text as sql_text
from decimal import Decimal

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

async def process_order(text: str, session: AsyncSession, phone: str = "console"):
    """Procesa una orden y la guarda en la base de datos"""
    try:
        # Buscar el formato #ORDER:{} en el texto
        if "#ORDER:" in text:
            order_json = text.split("#ORDER:")[1].strip()
            order_data = json.loads(order_json)
            
            # Obtener o crear usuario
            user_query = sql_text("""
                WITH new_user AS (
                    INSERT INTO hatsu.usuarios (telefono, source, fecha_registro)
                    SELECT :phone, 'whatsapp', CURRENT_TIMESTAMP
                    WHERE NOT EXISTS (
                        SELECT 1 FROM hatsu.usuarios WHERE telefono = :phone
                    )
                    RETURNING id, true as is_new
                )
                SELECT id, false as is_new FROM hatsu.usuarios WHERE telefono = :phone
                UNION ALL
                SELECT id, is_new FROM new_user
                LIMIT 1
            """)
            result = await session.execute(user_query, {"phone": phone})
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
            
            # Insertar la orden directamente usando SQL
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
            logger.info(f"Nueva orden {orden_id} guardada para {phone}")
            
            # Generar mensaje de confirmación formateado
            confirmation_message = _format_order_confirmation(order_data, user_address)
            return True, is_new_user, confirmation_message
            
    except Exception as e:
        logger.error(f"Error procesando orden: {str(e)}")
        await session.rollback()
        return False, False, None

async def update_user_data(text: str, session: AsyncSession, phone: str = "console"):
    """Actualiza los datos del usuario"""
    try:
        if "#USER_DATA:" in text:
            user_data_json = text.split("#USER_DATA:")[1].strip()
            user_data = json.loads(user_data_json)
            
            update_query = sql_text("""
                UPDATE hatsu.usuarios
                SET nombre = :nombre,
                    email = :email,
                    direccion = :direccion
                WHERE telefono = :phone
                RETURNING id
            """)
            
            result = await session.execute(
                update_query,
                {
                    "nombre": user_data.get("nombre"),
                    "email": user_data.get("email"),
                    "direccion": user_data.get("direccion"),
                    "phone": phone
                }
            )
            
            await session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Error actualizando datos de usuario: {str(e)}")
        await session.rollback()
        return False

async def get_user_data(session: AsyncSession, phone: str = "console"):
    """Obtiene los datos del usuario si existe"""
    try:
        query = sql_text("""
            SELECT nombre, direccion FROM hatsu.usuarios
            WHERE telefono = :phone AND (nombre IS NOT NULL OR direccion IS NOT NULL)
        """)
        result = await session.execute(query, {"phone": phone})
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

async def initialize_agent():
    """Inicializa el agente con el menú y los locales"""
    await init_db()
    logger.info("Base de datos inicializada")
    
    async with async_session() as session:
        from app.api.whatsapp_server import get_menu_from_db, get_locales_from_db
        
        menu = await get_menu_from_db(session)
        locales = await get_locales_from_db(session)
        
        if menu:
            agent = TestAIAgent(menu_data=menu, locales_data=locales)
            logger.info("Agente AI inicializado con menú y locales de la base de datos")
            return agent
        else:
            logger.warning("No se pudo obtener el menú de la base de datos")
            return None

async def chat_loop(agent: TestAIAgent):
    """Ejecuta el loop principal de chat"""
    print("\n¡Bienvenido al simulador de chat de Hatsu Sushi 🍣 - Vicente Lopez!")
    print("Escribe 'salir' para terminar la conversación.")
    print("-" * 50)
    
    async with async_session() as session:
        # Verificar si es un usuario existente y obtener sus datos
        user_data = await get_user_data(session, "console")
        if user_data:
            # Establecer los datos del usuario en el agente
            agent.set_user_data(
                name=user_data.get("nombre"),
                address=user_data.get("direccion")
            )
            print(f"\nBot: ¡Hola {user_data.get('nombre')}! ¡Bienvenido nuevamente!")
        
        while True:
            try:
                # Obtener input del usuario
                user_input = input("\nTú: ").strip()
                if user_input.lower() == 'salir':
                    print("\n¡Gracias por usar el simulador de chat! 👋")
                    break
                
                # Procesar mensaje con el agente
                full_response = await agent.process_message(user_input)
                
                # Separar el mensaje para el usuario del JSON técnico
                user_message = full_response
                if "#ORDER:" in full_response:
                    user_message = full_response.split("#ORDER:")[0].strip()
                    # Procesar la orden solo si viene de la consola
                    success, is_new_user, confirmation_message = await process_order(full_response, session, "console")
                    if success:
                        user_message = confirmation_message
                    else:
                        user_message += "\n\nLo siento, hubo un problema al procesar tu orden. Por favor, intenta nuevamente."
                
                if "#USER_DATA:" in full_response:
                    await update_user_data(full_response, session, "console")
                
                # Mostrar respuesta
                print("\nBot:", user_message)
                
            except Exception as e:
                logger.error(f"Error en el chat: {str(e)}")
                print("\nBot: Lo siento, ocurrió un error. ¿Podrías intentarlo de nuevo?")

async def main():
    """Función principal"""
    try:
        # Inicializar el agente
        agent = await initialize_agent()
        if agent:
            # Iniciar el loop de chat
            await chat_loop(agent)
        else:
            logger.error("No se pudo inicializar el agente")
            print("Error: No se pudo inicializar el sistema.")
    except Exception as e:
        logger.error(f"Error en main: {str(e)}")
        print("Error: Ocurrió un problema al iniciar el sistema.")

if __name__ == "__main__":
    asyncio.run(main()) 