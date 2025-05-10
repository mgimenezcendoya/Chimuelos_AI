import os
import logging
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text
from decimal import Decimal
import uuid
from datetime import datetime, timezone, timedelta
from dateutil import parser

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

def _format_order_confirmation(order_data: dict) -> str:
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
    if not order_data.get("is_takeaway", False) and order_data.get("direccion"):
        message.append(f"\n🏠 Dirección de entrega: {order_data['direccion']}")
    
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
            
            # Obtener nombre del usuario si existe
            user_name = None
            if not is_new_user:
                user_data_query = sql_text("""
                    SELECT nombre FROM hatsu.usuarios WHERE id = :usuario_id
                """)
                result = await session.execute(user_data_query, {"usuario_id": usuario_id})
                user_data = result.fetchone()
                if user_data:
                    user_name = user_data[0]
            
            # Crear la orden
            order_query = sql_text("""
                INSERT INTO hatsu.ordenes (
                    usuario_id,
                    local_id,
                    fecha_hora,
                    estado,
                    monto_total,
                    medio_pago,
                    is_takeaway,
                    origen,
                    observaciones,
                    direccion
                ) VALUES (
                    :usuario_id,
                    (SELECT id FROM hatsu.locales WHERE nombre = 'Vicente Lopez' LIMIT 1),
                    CURRENT_TIMESTAMP,
                    'pendiente',
                    :monto_total,
                    :medio_pago,
                    :is_takeaway,
                    :origen,
                    :observaciones,
                    :direccion
                ) RETURNING id
            """)
            
            result = await session.execute(
                order_query,
                {
                    "usuario_id": usuario_id,
                    "monto_total": order_data.get("total"),
                    "medio_pago": order_data.get("medio_pago"),
                    "is_takeaway": order_data.get("is_takeaway", True),
                    "origen": origen,
                    "observaciones": order_data.get("observaciones"),
                    "direccion": order_data.get("direccion") if not order_data.get("is_takeaway", True) else None
                }
            )
            orden_id = result.scalar_one()
            
            # Guardar los items de la orden
            for item in order_data.get("items", []):
                item_query = sql_text("""
                    INSERT INTO hatsu.orden_detalle (
                        orden_id,
                        producto_id,
                        cantidad,
                        precio_unitario,
                        subtotal
                    ) VALUES (
                        :orden_id,
                        (SELECT id FROM hatsu.productos WHERE nombre = :producto_nombre LIMIT 1),
                        :cantidad,
                        :precio_unitario,
                        :subtotal
                    )
                """)
                
                await session.execute(
                    item_query,
                    {
                        "orden_id": orden_id,
                        "producto_nombre": item["product"],
                        "cantidad": item["quantity"],
                        "precio_unitario": item["precio_unitario"],
                        "subtotal": item["subtotal"]
                    }
                )
            
            await session.commit()
            
            # Formatear mensaje de confirmación
            confirmation_message = _format_order_confirmation(order_data)
            
            return True, is_new_user, confirmation_message
            
    except Exception as e:
        logger.error(f"Error procesando orden: {str(e)}")
        await session.rollback()
        return False, False, str(e)

async def update_user_data(text: str, session: AsyncSession, phone: str, origen: str = "whatsapp"):
    """Actualiza los datos del usuario"""
    try:
        if "#USER_DATA:" in text:
            # Separar el JSON de la orden del resto del mensaje
            parts = text.split("#USER_DATA:")
            user_data_json = parts[1].split("\n\n")[0].strip()  # Tomar solo la parte del JSON
            user_data = json.loads(user_data_json)
            
            # Limpiar el número de teléfono si viene de WhatsApp
            clean_phone = phone.replace("whatsapp:", "")
            
            update_query = sql_text("""
                UPDATE hatsu.usuarios
                SET nombre = :nombre,
                    email = :email
                WHERE telefono = :phone AND origen = :origen
                RETURNING id
            """)
            
            result = await session.execute(
                update_query,
                {
                    "nombre": user_data.get("nombre"),
                    "email": user_data.get("email"),
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
    """Obtiene los datos del usuario y la dirección de su último pedido"""
    try:
        # Limpiar el número de teléfono si viene de WhatsApp
        clean_phone = phone.replace("whatsapp:", "")
        
        query = sql_text("""
            WITH user_data AS (
                SELECT u.id, u.nombre, u.email
                FROM hatsu.usuarios u
                WHERE u.telefono = :phone 
                AND u.origen = :origen 
                AND u.nombre IS NOT NULL
            ),
            last_order AS (
                SELECT o.direccion
                FROM hatsu.ordenes o
                JOIN user_data u ON o.usuario_id = u.id
                WHERE o.direccion IS NOT NULL
                ORDER BY o.fecha_hora DESC
                LIMIT 1
            )
            SELECT 
                u.nombre,
                u.email,
                lo.direccion
            FROM user_data u
            LEFT JOIN last_order lo ON true
        """)
        result = await session.execute(query, {"phone": clean_phone, "origen": origen})
        row = result.first()
        if row:
            return {
                "nombre": row[0],
                "email": row[1],
                "direccion": row[2]  # Dirección del último pedido
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
    media_url: str = None,
    tokens: int = None
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
        tokens: Número de tokens estimados (opcional)
    
    Returns:
        int: ID del mensaje guardado o None si hubo error
    """
    try:
        # Si no está explícitamente marcado como intervención humana,
        # verificar si estamos en modo humano
        if not intervencion_humana:
            intervencion_humana = await is_in_human_mode(session, usuario_id)

        # --- Lógica de sesión ---
        # Buscar el último mensaje del usuario (rol='usuario')
        last_msg_query = sql_text("""
            SELECT sesion_id, timestamp
            FROM hatsu.mensajes
            WHERE usuario_id = :usuario_id
              AND rol = 'usuario'
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        result = await session.execute(last_msg_query, {"usuario_id": usuario_id})
        row = result.first()
        now = None
        sesion_id = None
        if row and row[1]:
            last_timestamp = row[1]
            # Si viene como string, parsear a datetime
            if isinstance(last_timestamp, str):
                last_timestamp = parser.parse(last_timestamp)
            # Si es naive, asumir UTC
            if last_timestamp.tzinfo is None:
                last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            # Si el último mensaje fue hace menos de 12 horas, reutilizar el sesion_id
            if (now - last_timestamp).total_seconds() < 12 * 3600 and row[0]:
                sesion_id = row[0]
        if not sesion_id:
            sesion_id = str(uuid.uuid4())
        # --- Fin lógica de sesión ---

        # Guardar el mensaje
        query = sql_text("""
            INSERT INTO hatsu.mensajes (
                usuario_id, orden_id, rol, mensaje, timestamp, 
                canal, intervencion_humana, intervencion_humana_historial, leido,
                media_url, tokens, sesion_id
            ) VALUES (
                :usuario_id, :orden_id, :rol, :mensaje, CURRENT_TIMESTAMP,
                :canal, :intervencion_humana, :intervencion_humana, false,
                :media_url, :tokens, :sesion_id
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
                "media_url": media_url,
                "tokens": tokens,
                "sesion_id": sesion_id
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

async def get_user_session_message_count(session: AsyncSession, usuario_id: int):
    """Devuelve (count, sesion_id) de mensajes de usuario en la sesión activa actual (última sesión < 12hs)"""
    # Buscar la última sesión activa
    last_msg_query = sql_text("""
        SELECT sesion_id, timestamp
        FROM hatsu.mensajes
        WHERE usuario_id = :usuario_id
          AND rol = 'usuario'
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    result = await session.execute(last_msg_query, {"usuario_id": usuario_id})
    row = result.first()
    sesion_id = None
    if row and row[1]:
        last_timestamp = row[1]
        # Si viene como string, parsear a datetime
        if isinstance(last_timestamp, str):
            last_timestamp = parser.parse(last_timestamp)
        # Si es naive, asumir UTC
        if last_timestamp.tzinfo is None:
            last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        # Si la última sesión es menor a 12hs, usar ese sesion_id
        if (now - last_timestamp).total_seconds() < 12 * 3600 and row[0]:
            sesion_id = row[0]
    if not sesion_id:
        return 0, None
    # Contar mensajes de usuario en esa sesión
    count_query = sql_text("""
        SELECT COUNT(*) FROM hatsu.mensajes
        WHERE usuario_id = :usuario_id
          AND rol = 'usuario'
          AND sesion_id = :sesion_id
    """)
    result = await session.execute(count_query, {"usuario_id": usuario_id, "sesion_id": sesion_id})
    count = result.scalar_one()
    return count, sesion_id 