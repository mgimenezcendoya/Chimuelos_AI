import asyncio
import os
import json
import logging
from dotenv import load_dotenv
from openai import AsyncOpenAI
from typing import Dict, Any
from pathlib import Path
import re
from datetime import datetime, timezone, timedelta

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

class TestAIAgent:
    def __init__(self, menu_data=None, locales_data=None):
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.conversation_history = []
        self.menu_data = menu_data if menu_data else {}
        self.locales_data = locales_data if locales_data else {}
        # Atributos para datos del usuario
        self.user_name = None
        self.user_email = None
        self.last_order_address = None  # Dirección del último pedido
        self.address_confirmed = False
        self.waiting_for_address_confirmation = False
        self.current_order = None
        self.current_order_json = None
        # Mantener un diccionario de productos activos
        self.active_products = self._build_active_products_dict()
        logger.info("TestAIAgent inicializado correctamente")
    
    def _build_active_products_dict(self) -> dict:
        """Construye un diccionario de productos activos con sus precios"""
        active_products = {}
        if not self.menu_data:
            return active_products
            
        # Recorrer todas las secciones del menú
        for section_key, section in self.menu_data.items():
            for item in section.get('items', []):
                # Guardar el nombre del producto y su precio
                active_products[item['name']] = {
                    'price': item['price'],
                    'description': item.get('description', '')
                }
        
        return active_products
    
    def validate_order_items(self, order_data: dict) -> tuple[bool, str]:
        """Valida que todos los productos en la orden existan y estén activos
        
        Args:
            order_data: Diccionario con los datos de la orden
            
        Returns:
            tuple[bool, str]: (True si la orden es válida, mensaje de error si no lo es)
        """
        if not order_data or 'items' not in order_data:
            return False, "La orden no contiene items"
            
        # Validar que exista el campo observaciones
        if 'observaciones' not in order_data:
            return False, "La orden debe incluir el campo observaciones"
            
        # Validar que exista el campo horario_entrega
        if 'horario_entrega' not in order_data:
            return False, "La orden debe incluir el campo horario_entrega"
            
        for item in order_data['items']:
            product_name = item.get('product')
            if not product_name:
                return False, "Hay un item sin nombre de producto"
                
            if product_name not in self.active_products:
                return False, f"El producto '{product_name}' no existe o no está activo"
                
            # Validar que el precio sea correcto
            expected_price = self.active_products[product_name]['price']
            item_price = int(float(str(item.get('precio_unitario', 0))))
            if item_price != expected_price:
                return False, f"El precio del producto '{product_name}' no coincide con el precio actual"
                
            # Validar que el subtotal sea correcto
            quantity = int(float(str(item.get('quantity', 0))))
            expected_subtotal = expected_price * quantity
            item_subtotal = int(float(str(item.get('subtotal', 0))))
            if item_subtotal != expected_subtotal:
                return False, f"El subtotal del producto '{product_name}' no es correcto"
        
        return True, ""
    
    def set_user_data(self, name=None, email=None, last_order_address=None):
        """Establece los datos del usuario"""
        if name:
            self.user_name = name
        if email:
            self.user_email = email
        if last_order_address:
            self.last_order_address = last_order_address
            # Marcar la dirección como confirmada si se establece desde la base de datos
            self.address_confirmed = True
    
    def get_user_data(self):
        """Obtiene los datos del usuario"""
        return {
            "name": self.user_name,
            "email": self.user_email,
            "last_order_address": self.last_order_address
        }
    
    def _format_menu_for_prompt(self) -> str:
        """Formatea el menú para el prompt del sistema"""
        if not self.menu_data:
            return "Error: Menú no disponible"
        
        menu_text = []
        
        for section_key, section in self.menu_data.items():
            menu_text.append(f"\n{section['title']}")
            if 'description' in section:
                menu_text.append(f"({section['description']})")
            
            for item in section['items']:
                item_line = []
                item_line.append(f"- {item['name']}")
                
                if 'price' in item:
                    item_line.append(f"(${int(float(item['price']))})")
                
                if 'description' in item:
                    item_line.append(f": {item['description']}")
                
                if 'includes' in item:
                    item_line.append("\n  * " + "\n  * ".join(item['includes']))
                
                if 'availability' in item:
                    item_line.append(f" ({item['availability']})")
                
                menu_text.append("".join(item_line))
        
        return "\n".join(menu_text)
    
    def _format_locales_for_prompt(self) -> str:
        """Formatea la información de locales para el prompt del sistema"""
        if not self.locales_data or not self.locales_data.get("locations"):
            return "Información de locales no disponible"
        
        locales_text = [f"\n{self.locales_data['title']}"]
        
        for local in self.locales_data["locations"]:
            local_info = []
            local_info.append(f"- {local['name']}")
            if local.get('address'):
                local_info.append(f"\n  Dirección: {local['address']}")
            if local.get('phone'):
                local_info.append(f"\n  Teléfono: {local['phone']}")
            locales_text.append("".join(local_info))
        
        return "\n".join(locales_text)
    
    def _get_current_time(self) -> str:
        """Obtiene la hora actual en UTC-3 (Argentina)"""
        utc_now = datetime.now(timezone.utc)
        argentina_time = utc_now - timedelta(hours=3)
        return argentina_time.strftime("%H:%M")
    
    async def process_message(self, message: str, media_url: str = None) -> str:
        """
        Procesa un mensaje del usuario y retorna una respuesta.
        
        Args:
            message (str): El mensaje del usuario
            media_url (str, optional): URL de la imagen si el mensaje incluye una
            
        Returns:
            str: La respuesta del agente
        """
        try:
            logger.info(f"Procesando mensaje: {message}")
            if media_url:
                logger.info(f"Media URL recibida: {media_url}")
                return "He recibido tu imagen. Por el momento no puedo procesarla, pero un operador humano la revisará pronto. ¿En qué más puedo ayudarte?"
            
            # Obtener la hora actual en UTC-3
            current_time = self._get_current_time()
            
            # Si no tenemos el nombre del usuario o está vacío, solicitarlo primero
            if not self.user_name or self.user_name.strip() == '':
                # Si es el primer mensaje, pedir el nombre
                if not self.conversation_history:
                    # Guardar el mensaje en el historial
                    self.conversation_history.append({"role": "user", "content": f"[Hora actual: {current_time}] {message}"})
                    response = "¡Bienvenido a Hatsu Sushi - Vicente Lopez! Para brindarte una mejor atención, ¿podrías decirme tu nombre?"
                    self.conversation_history.append({"role": "assistant", "content": response})
                    return response
                
                # Si ya pedimos el nombre, el siguiente mensaje es el nombre
                formatted_name = ' '.join(word.capitalize() for word in message.split())
                self.user_name = formatted_name  # Guardar el nombre en la instancia
                user_data = {"nombre": formatted_name}
                response = f"¡Gracias {formatted_name}! ¿En qué puedo ayudarte hoy?\n\n"
                response += "🍣 Podés ver nuestro menú completo en: https://pedidos.masdelivery.com/hatsu-sushi\n"
                response += "✍️ ¿Qué te gustaría ordenar?"
                
                # Guardar el mensaje en el historial
                self.conversation_history.append({"role": "user", "content": f"[Hora actual: {current_time}] {message}"})
                self.conversation_history.append({"role": "assistant", "content": response})
                
                return response + f"\n\n#USER_DATA:{json.dumps(user_data)}"
            
            # Si ya tenemos el nombre, proceder con el flujo normal
            messages = [
                {
                    "role": "system",
                    "content": self._get_system_prompt()
                }
            ]
            
            # Agregar historial de conversación
            messages.extend(self.conversation_history)
            
            # Agregar mensaje actual con la hora
            messages.append({"role": "user", "content": f"[Hora actual: {current_time}] {message}"})
            
            logger.info("Enviando solicitud a OpenAI")
            # Generar respuesta
            response = await self.client.chat.completions.create(
                model=os.getenv("GPT_MODEL", "gpt-4o"),
                messages=messages,
                temperature=0.7,
                max_tokens=500  # Aumentado para manejar respuestas más largas
            )
            
            response_text = response.choices[0].message.content
            logger.info(f"Respuesta recibida de OpenAI: {response_text}")
            
            # Validar orden si existe
            if "#ORDER:" in response_text:
                logger.info("Detectada orden en la respuesta")
                try:
                    # Separar el JSON de la orden del resto del mensaje
                    parts = response_text.split("#ORDER:")
                    message_before_order = parts[0].strip()
                    order_json = parts[1].split("\n\n")[0].strip()  # Tomar solo la parte del JSON
                    message_after_order = "\n\n".join(parts[1].split("\n\n")[1:]).strip()  # Resto del mensaje
                    
                    logger.info(f"Parte de orden a procesar: {order_json}")
                    order_data = json.loads(order_json)
                    logger.info(f"Orden parseada correctamente: {order_data}")
                    is_valid, error_msg = self.validate_order_items(order_data)
                    
                    if not is_valid:
                        logger.warning(f"Orden inválida: {error_msg}")
                        response_text = f"{message_before_order}\n\nLo siento, no puedo procesar tu orden: {error_msg}"
                    else:
                        # Si la orden es válida, mantener el mensaje original incluyendo la solicitud del comprobante
                        response_text = f"{message_before_order}\n\n#ORDER:{order_json}"
                        if message_after_order:
                            response_text += f"\n\n{message_after_order}"
                except json.JSONDecodeError as e:
                    logger.error(f"Error decodificando JSON de la orden: {str(e)}")
                    response_text = "Lo siento, hubo un error procesando tu orden. Por favor, intenta nuevamente."
                except Exception as e:
                    logger.error(f"Error procesando orden: {str(e)}")
                    response_text = "Lo siento, hubo un error procesando tu orden. Por favor, intenta nuevamente."
            
            # Guardar la conversación
            self.conversation_history.append({"role": "user", "content": f"[Hora actual: {current_time}] {message}"})
            self.conversation_history.append({"role": "assistant", "content": response_text})
            
            return response_text
        except Exception as e:
            logger.error(f"Error en process_message: {str(e)}")
            return "Lo siento, hubo un error procesando tu mensaje. Por favor, intenta nuevamente."
    
    def _get_system_prompt(self) -> str:
        """Obtiene el prompt del sistema"""
        menu_str = self._format_menu_for_prompt()
        locales_str = self._format_locales_for_prompt()
        
        # Determinar si el usuario tiene dirección registrada
        has_registered_address = "true" if self.last_order_address else "false"
        registered_address = self.last_order_address if self.last_order_address else "ninguna"
        has_user_name = "true" if self.user_name else "false"
        user_name = self.user_name if self.user_name else "ninguno"
        
        return f"""Eres un asistente virtual de Hatsu Sushi - Vicente Lopez.
        Tu objetivo es ayudar a los clientes a realizar pedidos y responder sus consultas.
        
        Estado actual del usuario:
        - Nombre registrado: {has_user_name}
        - Nombre: {user_name}
        - Existe dirección del último pedido: {has_registered_address}
        - Dirección del último pedido: {registered_address}
        
        CRÍTICO - Flujo de Saludo:
        1. Si es la primera interacción del chat:
           - Si el usuario está registrado (nombre conocido):
             * Saluda usando su nombre: "👋 Hola {user_name}! Qué bueno que estés de vuelta."
           - Si el usuario no está registrado:
             * Usa el saludo genérico: "👋 Hola! Este es el chat de Hatsu Sushi, Vicente Lopez."
           - SIEMPRE incluye los siguiente mensajes después del saludo, sin utilizar formato markdown para la URL y respetando el espacio entre el emoji y el texto:
             "🍣 Podés ver nuestro menú completo en: https://pedidos.masdelivery.com/hatsu-sushi"
             "✍️  Qué te gustaría ordenar?"
        2. Para el resto de las interacciones:
           - Mantén un tono amigable pero profesional
           - Puedes usar el nombre del usuario si está registrado
        
        Reglas:
        1. Sé amable y profesional
        2. Habla en español
        3. Si el cliente solicita hablar con un humano, indícalo claramente
        4. Verifica los datos del pedido antes de confirmarlo
        5. Mantén un tono conversacional pero eficiente
        6. Sugiere promociones cuando sea apropiado
        7. Si el cliente pregunta por locales, proporciona la información detallada
        8. IMPORTANTE: Solo puedes tomar pedidos para el local de Vicente Lopez. Si el cliente quiere ordenar en otro local, explica amablemente que por el momento solo se pueden hacer pedidos para Vicente Lopez, pero puedes proporcionarle la información de contacto del local que desea

        CRÍTICO - Menú y Nombres de Productos:
        SOLO puedes referirte a los nombres de los productos tanto en la conversación como en la conformación del JSON #ORDER tal cual aparecen en el campo "nombre" del siguiente menú:
        {menu_str}
        
        Reglas específicas sobre nombres de productos:
        1. DURANTE TODA LA CONVERSACIÓN usa EXACTAMENTE el nombre que aparece en el menú
        2. NO modifiques, acortes ni cambies los nombres en ningún momento
        3. NO agregues palabras como "Roll" si no están en el nombre original
        4. Ejemplo: Si el menú dice "Azteca x 10pz", NO digas "Roll Azteca x 10pz"
        5. Un producto es válido SOLO si existe exactamente en el menú
        6. Si el producto no existe en el menú, NO es válido
        7. Si la validación falla, informa inmediatamente al usuario

        CRÍTICO - Manejo de Productos No Encontrados:
        Cuando un cliente solicite un producto que no existe exactamente en el menú:
        1. SIEMPRE responde con el siguiente formato:
           "Lo siento, pero el [nombre del producto solicitado] no está disponible en nuestro menú. Sin embargo, puedo ofrecerte:
           
           - [Producto similar 1] ($[precio])
           - [Producto similar 2] ($[precio])
           - [Producto similar 3] ($[precio])"
        
        2. Busca productos similares basándose en:
           - Palabras clave en el nombre
           - Ingredientes similares
           - Tipo de roll (clásico, especial, etc.)
        
        3. SIEMPRE incluye el precio de cada producto sugerido
        4. SIEMPRE usa el formato exacto de precios ($XXXXX)
        5. SIEMPRE usa guiones (-) para listar las alternativas
        6. SIEMPRE incluye al menos una alternativa si existe un producto similar
        7. Si no hay productos similares, responde:
           "Lo siento, pero el [nombre del producto solicitado] no está disponible en nuestro menú. ¿Te gustaría ver nuestro menú completo?"

        CRÍTICO - Flujo de Confirmación:
            a. NO preguntes por método de envío ni pago hasta que:
               - Hayas verificado la disponibilidad de todos los productos
               - El cliente haya confirmado el pedido con los productos disponibles
               - NUNCA debes decirle al cliente que estás verificando la disponibilidad
            b. Una vez confirmado el pedido con productos disponibles:
               - PRIMERO pregunta si desea retirar el pedido o envío a domicilio
               - DESPUÉS pregunta el método de pago (Efectivo o MercadoPago)
               - SIEMPRE pregunta por requerimientos especiales DESPUÉS de confirmar el método de pago
               - Si elige retirarlo:
                 * Incluye el formato #ORDER con is_takeaway:true y el medio_pago elegido
               - Si elige envío a domicilio:
                 * Si tiene dirección del último pedido ({registered_address}), ofrécele enviarlo a esa dirección
                 * Si no tiene dirección, simplemente pregunta: "¿Cuál es la dirección de entrega?"
                 * IMPORTANTE: Cuando el cliente proporcione la dirección, DEBES incluirla en el campo "direccion" del #ORDER
                 * El formato #ORDER DEBE incluir:
                   - is_takeaway:false
                   - medio_pago: el método elegido
                   - direccion: la dirección proporcionada por el cliente
               c. IMPORTANTE: Las observaciones del cliente SIEMPRE deben guardarse en el campo observaciones del #ORDER
               d. PROHIBIDO confirmarle el pedido final a un usuario sin generar #ORDER 
               e. CRÍTICO: Si es una orden de delivery (is_takeaway:false), el campo "direccion" es OBLIGATORIO en el #ORDER

        CRÍTICO - Al preguntar por requerimientos especiales:
            - SIEMPRE usa EXACTAMENTE la frase: "¿Tienes algún requerimiento especial para tu pedido?"
            - NUNCA agregues ejemplos ni sugerencias
            - NUNCA modifiques esta pregunta
            - NUNCA agregues texto adicional antes o después de la pregunta
            - SIEMPRE pregunta esto DESPUÉS de confirmar el método de pago
            - Las observaciones del cliente se guardarán en el campo observaciones del #ORDER

        Información de Locales:
        {locales_str}
        
        Formatos de respuesta especiales (no mostrar al cliente):
        - Para crear un pedido: #ORDER:{{
            "total": 1234,
            "items": [
                {{
                    "product": "nombre",
                    "quantity": 1,
                    "precio_unitario": 1234,
                    "subtotal": 1234
                }}
            ],
            "is_takeaway": false,
            "medio_pago": "efectivo/mercadopago",
            "observaciones": "texto con requerimientos especiales",
            "direccion": "dirección de entrega provista por el cliente para este pedido (solo si is_takeaway es false)",
            "horario_entrega": "Entrega inmediata"
        }}
        - Para derivar a humano: #HUMAN
        - Para guardar datos de usuario: #USER_DATA:{{
            "nombre": "Juan Pérez",
            "email": "juan@email.com"
        }}

        IMPORTANTE: Al mostrar precios en cualquier mensaje, asegúrate de:
        1. Usar el símbolo $ antes del número
        2. Usar puntos como separadores de miles
        3. No mostrar decimales
        4. Ejemplos de formato correcto:
           - $1.200
           - $15.750
           - $170.190
        5. Ejemplos de formato incorrecto:
           - $1200
           - $15750
           - $170190

        IMPORTANTE: Al calcular el total del pedido en el mensaje de confirmación previo, asegúrate de:
        1. Usar el precio_unitario correcto para cada item
        2. Calcular el subtotal como precio_unitario * cantidad
        3. Sumar todos los subtotales para obtener el total
        4. Mostrar el total de manera concisa como "Total: $XXXXX" sin desglosar los subtotales
        5. Ejemplo de formato correcto:
           - 10x Milanesa de pollo con papas fritas ($15.750 c/u)
           - 1x Azteca x 10pz ($12.690)
           Total: $170.190
           
           ¿Deseas confirmar este pedido?

        Ejemplo de flujo con productos parcialmente disponibles:
        Cliente: "Quiero una milanesa y un Salmon premium x 15pz"
        Tú: "Lo siento, el Salmon premium x 15pz no está disponible en este momento.
        Sin embargo, puedo ofrecerte:
        - 1 Milanesa de pollo con papas fritas ($15.750)
        Total: $15.750
        
        ¿Deseas confirmar este pedido con los productos disponibles?"

        Cliente: "sí"
        Tú: "¡Perfecto! ¿Deseas retirar el pedido en nuestro local de Vicente Lopez o prefieres que te lo enviemos a domicilio?"

        Cliente: "lo retiro"
        Tú: "¿Cómo deseas realizar el pago? Las opciones son: Efectivo o MercadoPago"

        Cliente: "mercadopago"
        Tú: "¿Tienes algún requerimiento especial para tu pedido?"

        Cliente: "si, sin sal"
        Tú: "¡Excelente! Tu pedido estará listo para retirar en nuestro local de Vicente Lopez. Te avisaremos cuando puedas pasar a buscarlo."

        #ORDER:{{
            "total": 15750,
            "items": [
                {{
                    "product": "Milanesa de pollo con papas fritas",
                    "quantity": 1,
                    "precio_unitario": 15750,
                    "subtotal": 15750
                }}
            ],
            "is_takeaway": true,
            "medio_pago": "mercadopago",
            "observaciones": "sin sal"
        }}

        CRÍTICO - Manejo del horario de entrega:
        1. El campo horario_entrega SIEMPRE debe estar presente en el #ORDER
        2. Por defecto, usar "Entrega inmediata"
        3. NO preguntar al usuario por el horario de entrega como parte del flujo normal
        4. Solo capturar un horario específico si el usuario lo solicita explícitamente
        5. EXCEPCIÓN - Si la hora actual es anterior a las 19:00hs:
           - SIEMPRE preguntar al usuario: "¿Deseas programar el pedido para cierta hora o prefieres entrega inmediata?" si la hora actual es anterior a las 19:00hs
            - NUNCA usar "Entrega inmediata" como valor por defecto si la hora actual es anterior a las 19:00hs
           - Si el usuario elige programar el pedido:
             * Validar que la hora solicitada sea posterior a las 19:00hs
             * Si el usuario solicita una hora antes de las 19:00hs, informar:
               "Lo siento, nuestro local realiza entregas a partir de las 19:00hs. ¿Te gustaría programar tu pedido para después de las 19:00hs?"
        6. Al capturar un horario específico:
           - Usar formato "HH:MMhs" (ej: "21:00hs")
           - Si el usuario dice "a las 9" o "nueve", asumir PM (21:00hs)
           - Si el usuario dice "21" o "21hs", usar "21:00hs"
        7. Ejemplos de conversión:
           - "a las 9" -> "21:00hs"
           - "nueve y media" -> "21:30hs"
           - "21" -> "21:00hs"
           - "21hs" -> "21:00hs"

        CRÍTICO - Validación de horarios de entrega:
        1. Tiempo mínimo de entrega:
           - El horario de entrega solicitado debe ser al menos 40 minutos después de la hora actual
           - Si el usuario solicita un horario muy cercano (menos de 40 minutos), informar:
             "Lo siento, necesitamos al menos 40 minutos para preparar y entregar tu pedido. ¿Te gustaría programarlo para [hora actual + 40 minutos]?"
           - Ejemplo: Si son las 21:00 y el usuario pide para las 21:15, sugerir las 21:40

        2. Solicitudes de tiempo relativo:
           - Si el usuario solicita entrega en un tiempo relativo (ej: "en 45 minutos"), calcular:
             * Tomar la hora actual (que viene en el formato [Hora actual: HH:MM])
             * Sumar los minutos o horas solicitados
             * Convertir al formato "HH:MMhs"
           - Ejemplos:
             * Si son las 21:00 y pide "en 45 minutos" -> "21:45hs"
             * Si son las 21:30 y pide "en 1 hora y media" -> "23:00hs"
             * Si son las 21:45 y pide "en 2 horas" -> "23:45hs"

        3. Validación de horario mínimo:
           - CRÍTICO: NO se permiten entregas antes de las 19:00hs en ningún caso
           - Si la hora actual es anterior a las 19:00hs:
             * Si el usuario elige programar el pedido:
               - Validar que la hora solicitada sea posterior a las 19:00hs
               - Si el usuario solicita una hora antes de las 19:00hs, informar:
                 "Lo siento, nuestro local realiza entregas a partir de las 19:00hs. ¿Te gustaría programar tu pedido para después de las 19:00hs?"
             * Si el usuario elige entrega inmediata:
               - Informar: "Lo siento, nuestro local realiza entregas a partir de las 19:00hs. ¿Te gustaría programar tu pedido para después de las 19:00hs?"
           - Si el usuario programa el pedido para un horario anterior a la hora actual, informarle del error y volver a preguntar por el horario de entrega
             * Seguir las reglas normales de validación de tiempo mínimo (40 minutos)
           - Si la hora actual es posterior a las 19:00hs:
             * Seguir las reglas normales de validación de tiempo mínimo (40 minutos)

        IMPORTANTE: Al mostrar precios en cualquier mensaje
        """

    async def initialize_user_data(self, session, phone, origen="whatsapp"):
        """
        Inicializa los datos del usuario si existe en la base de datos.
        
        Args:
            session: Sesión de base de datos
            phone: Número de teléfono del usuario
            origen: Origen del usuario (whatsapp, console, etc.)
            
        Returns:
            bool: True si el usuario existe y se cargaron sus datos
        """
        try:
            from app.utils.db_utils import get_user_data
            user_data = await get_user_data(session, phone, origen)
            if user_data:
                self.set_user_data(
                    name=user_data.get("nombre"),
                    email=user_data.get("email"),
                    last_order_address=user_data.get("direccion")
                )
                logger.info(f"Datos del usuario cargados: {user_data}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error al inicializar datos del usuario: {str(e)}")
            return False

    def estimate_prompt_tokens(self, user_message: str) -> int:
        """Cuenta los caracteres del prompt completo y divide entre 4 (mínimo 1)."""
        mensajes = [
            {"role": "system", "content": self._get_system_prompt()}
        ] + self.conversation_history + [
            {"role": "user", "content": user_message}
        ]
        texto_completo = "".join(m["content"] for m in mensajes)
        return max(1, len(texto_completo) // 4)

async def main():
    agent = TestAIAgent()
    print("¡Bienvenido al sistema de prueba de Hatsu Sushi - Vicente Lopez!")
    print("Escribe 'salir' para terminar la conversación.")
    print("-" * 50)
    
    # Inicializar base de datos y sesión
    from app.database.database import init_db, async_session
    await init_db()
    
    async with async_session() as session:
        # Intentar cargar datos del usuario de consola
        await agent.initialize_user_data(session, "console", "console")
    
    while True:
        user_input = input("\nTú: ")
        if user_input.lower() == 'salir':
            break
        
        try:
            response = await agent.process_message(user_input)
            print("\nAgente:", response)
        except Exception as e:
            print(f"\nError: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 