import os
import logging
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text
from decimal import Decimal

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def get_menu_from_db(session: AsyncSession):
    """Obtiene el menú desde la base de datos"""
    try:
        # Consultar todos los productos activos
        logger.info("Consultando productos activos...")
        query = sql_text("""
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
        query = sql_text("""
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

async def process_order(text: str, session: AsyncSession, phone: str, origen: str = "whatsapp"):
    """Procesa una orden y la guarda en la base de datos"""
    try:
        # Buscar el formato #ORDER:{} en el texto
        if "#ORDER:" in text:
            order_json = text.split("#ORDER:")[1].strip()
            order_data = json.loads(order_json)
            
            # Obtener o crear usuario
            user_query = sql_text("""
                WITH new_user AS (
                    INSERT INTO hatsu.usuarios (telefono, origen, fecha_registro)
                    SELECT :phone, :origen, CURRENT_TIMESTAMP
                    WHERE NOT EXISTS (
                        SELECT 1 FROM hatsu.usuarios 
                        WHERE telefono = :phone AND origen = :origen
                    )
                    RETURNING id, true as is_new
                )
                SELECT id, false as is_new FROM hatsu.usuarios 
                WHERE telefono = :phone AND origen = :origen
                UNION ALL
                SELECT id, is_new FROM new_user
                LIMIT 1
            """)
            
            result = await session.execute(
                user_query,
                {
                    "phone": phone.replace("whatsapp:", ""),
                    "origen": origen
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
                    usuario_id, local_id, fecha_hora, estado, monto_total, 
                    medio_pago, is_takeaway, origen, observaciones
                ) VALUES (
                    :usuario_id, :local_id, CURRENT_TIMESTAMP, 'pendiente', :monto_total, 
                    :medio_pago, :is_takeaway, :origen, :observaciones
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
                    "medio_pago": order_data.get("medio_pago", "pendiente"),
                    "origen": origen,
                    "observaciones": order_data.get("observaciones", "")
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
            logger.info(f"Nueva orden {orden_id} guardada para {phone} desde {origen}")
            
            # Generar mensaje de confirmación formateado
            confirmation_message = _format_order_confirmation(order_data, user_address)
            return True, is_new_user, confirmation_message
            
    except Exception as e:
        logger.error(f"Error procesando orden: {str(e)}")
        await session.rollback()
        return False, False, None

async def update_user_data(text: str, session: AsyncSession, phone: str, origen: str = "whatsapp"):
    """Actualiza los datos del usuario"""
    try:
        if "#USER_DATA:" in text:
            user_data_json = text.split("#USER_DATA:")[1].strip()
            user_data = json.loads(user_data_json)
            
            # Limpiar el número de teléfono si viene de WhatsApp
            clean_phone = phone.replace("whatsapp:", "")
            
            update_query = sql_text("""
                UPDATE hatsu.usuarios
                SET nombre = :nombre,
                    email = :email,
                    direccion = :direccion
                WHERE telefono = :phone AND origen = :origen
                RETURNING id
            """)
            
            result = await session.execute(
                update_query,
                {
                    "nombre": user_data.get("nombre"),
                    "email": user_data.get("email"),
                    "direccion": user_data.get("direccion"),
                    "phone": clean_phone,
                    "origen": origen
                }
            )
            
            await session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Error actualizando datos de usuario: {str(e)}")
        await session.rollback()
        return False

async def get_user_data(session: AsyncSession, phone: str, origen: str = "whatsapp"):
    """Obtiene los datos del usuario si existe"""
    try:
        # Limpiar el número de teléfono si viene de WhatsApp
        clean_phone = phone.replace("whatsapp:", "")
        
        query = sql_text("""
            SELECT nombre, direccion FROM hatsu.usuarios
            WHERE telefono = :phone 
            AND origen = :origen 
            AND (nombre IS NOT NULL OR direccion IS NOT NULL)
        """)
        result = await session.execute(query, {"phone": clean_phone, "origen": origen})
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

async def is_in_human_mode(session: AsyncSession, usuario_id: int) -> bool:
    """Verifica si la conversación está en modo de intervención humana
    
    Args:
        session: Sesión de base de datos
        usuario_id: ID del usuario
    
    Returns:
        bool: True si está en modo humano, False si no
    """
    try:
        # Simplemente verificar si hay un mensaje con intervención humana en las últimas 2 horas
        query = sql_text("""
            SELECT EXISTS (
                SELECT 1
                FROM hatsu.mensajes
                WHERE usuario_id = :usuario_id
                AND intervencion_humana = true
                AND timestamp > NOW() - INTERVAL '2 hours'
            )
        """)
        
        result = await session.execute(query, {"usuario_id": usuario_id})
        return result.scalar_one() or False
        
    except Exception as e:
        logger.error(f"Error verificando modo humano: {str(e)}")
        return False

async def save_message(
    session: AsyncSession,
    usuario_id: int,
    mensaje: str,
    rol: str,
    orden_id: int = None,
    canal: str = "whatsapp",
    intervencion_humana: bool = False,
    media_url: str = None
):
    """Guarda un mensaje en la tabla hatsu.mensajes
    
    Args:
        session: Sesión de base de datos
        usuario_id: ID del usuario que participa en la conversación
        mensaje: Texto del mensaje
        rol: Rol del mensaje ('usuario', 'agente', 'humano', 'sistema')
        orden_id: ID de la orden relacionada (opcional)
        canal: Canal del mensaje ('console', 'whatsapp', 'web')
        intervencion_humana: Si el mensaje fue parte de una intervención humana
        media_url: URL de la imagen adjunta al mensaje (opcional)
    
    Returns:
        int: ID del mensaje guardado o None si hubo error
    """
    try:
        # Si no está explícitamente marcado como intervención humana,
        # verificar si estamos en modo humano
        if not intervencion_humana:
            intervencion_humana = await is_in_human_mode(session, usuario_id)
        
        # Guardar el mensaje
        query = sql_text("""
            INSERT INTO hatsu.mensajes (
                usuario_id, orden_id, rol, mensaje, timestamp, 
                canal, intervencion_humana, intervencion_humana_historial, leido,
                media_url
            ) VALUES (
                :usuario_id, :orden_id, :rol, :mensaje, CURRENT_TIMESTAMP,
                :canal, :intervencion_humana, :intervencion_humana, false,
                :media_url
            )
            RETURNING id
        """)
        
        result = await session.execute(
            query,
            {
                "usuario_id": usuario_id,
                "orden_id": orden_id,
                "rol": rol,
                "mensaje": mensaje,
                "canal": canal,
                "intervencion_humana": intervencion_humana,
                "media_url": media_url
            }
        )
        
        await session.commit()
        return result.scalar_one()
    except Exception as e:
        logger.error(f"Error guardando mensaje: {str(e)}")
        await session.rollback()
        return None

async def mark_conversation_for_human(session: AsyncSession, usuario_id: int, canal: str = "whatsapp"):
    """Marca la conversación para intervención humana y notifica al equipo de soporte
    
    Args:
        session: Sesión de base de datos
        usuario_id: ID del usuario que necesita ayuda
        canal: Canal de la conversación
    
    Returns:
        bool: True si se marcó correctamente, False si hubo error
    """
    try:
        # Obtener información del usuario
        user_query = sql_text("""
            SELECT telefono, nombre, direccion 
            FROM hatsu.usuarios 
            WHERE id = :usuario_id
        """)
        result = await session.execute(user_query, {"usuario_id": usuario_id})
        user_data = result.fetchone()
        
        if not user_data:
            logger.error(f"Usuario {usuario_id} no encontrado")
            return False
        
        # Guardar mensaje de transición amigable para el usuario
        transition_msg = (
            "🔄 Esta conversación ha sido derivada a un operador humano. "
            "En breve un miembro de nuestro equipo se pondrá en contacto contigo. "
            "La asistencia humana estará disponible durante las próximas 2 horas. "
            "Gracias por tu paciencia."
        )
        
        await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=transition_msg,
            rol="sistema",
            canal=canal,
            intervencion_humana=True  # Forzar intervencion_humana=True
        )
        
        # Guardar mensaje para el equipo de soporte en Retool
        support_msg = (
            f"⚠️ ATENCIÓN REQUERIDA\n"
            f"Usuario: {user_data.nombre or 'Sin nombre'}\n"
            f"Teléfono: {user_data.telefono}\n"
            f"Dirección: {user_data.direccion or 'No registrada'}\n"
            f"Canal: {canal}\n"
            f"Por favor, continúe la conversación desde Retool."
        )
        
        await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=support_msg,
            rol="sistema",
            canal=canal,
            intervencion_humana=True  # Forzar intervencion_humana=True
        )
        
        await session.commit()
        return True
        
    except Exception as e:
        logger.error(f"Error marcando conversación para intervención humana: {str(e)}")
        await session.rollback()
        return False

async def end_human_intervention(session: AsyncSession, usuario_id: int, canal: str = "whatsapp"):
    """Finaliza la intervención humana y retorna al modo agente
    
    Args:
        session: Sesión de base de datos
        usuario_id: ID del usuario
        canal: Canal de la conversación
    
    Returns:
        bool: True si se finalizó correctamente, False si hubo error
    """
    try:
        # Guardar mensaje de transición
        transition_msg = (
            "✅ La conversación ha vuelto al modo automático. "
            "¿En qué más puedo ayudarte?"
        )
        
        await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=transition_msg,
            rol="agente",
            canal=canal,
            intervencion_humana=False
        )
        
        await session.commit()
        return True
        
    except Exception as e:
        logger.error(f"Error finalizando intervención humana: {str(e)}")
        await session.rollback()
        return False 