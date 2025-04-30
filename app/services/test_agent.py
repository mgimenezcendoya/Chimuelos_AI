import asyncio
import os
import json
import yaml
import logging
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from typing import Dict, Any, List
from pathlib import Path
import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text as sql_text

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

class TestAIAgent:
    def __init__(self):
        self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-20250219")
        self.conversation_history = []
        self.user_name = None
        self.user_email = None
        self.user_address = None
        self.address_confirmed = False
        self.waiting_for_address_confirmation = False
        self.current_order = None
        self.current_order_json = None
        self.db_pool = None
        self.db_schema = self._load_db_schema()
        self.prompt_cache = {}  # Diccionario para cachear las diferentes versiones del prompt
        self.max_history_pairs = 3  # Mantener los últimos 3 pares de mensajes
        self._last_menu = None
        self._last_locations = None
    
    def _load_db_schema(self) -> Dict:
        """Carga el esquema de la base de datos desde el archivo YAML"""
        schema_path = Path(__file__).parent.parent / 'schema' / 'db_schema.yaml'
        with open(schema_path, 'r') as f:
            return yaml.safe_load(f)

    def _format_schema_for_prompt(self) -> str:
        """Formatea el esquema de la base de datos para el prompt"""
        schema_text = ["ESQUEMA DE LA BASE DE DATOS:"]
        for i, (table_name, table_info) in enumerate(self.db_schema.items(), 1):
            schema_text.append(f"{i}. {table_name}:")
            if 'description' in table_info:
                schema_text.append(f"   {table_info['description']}")
            for col_name, col_type in table_info['columns'].items():
                schema_text.append(f"   - {col_name}: {col_type}")
        return "\n".join(schema_text)

    async def init_db(self):
        """Inicializa la conexión a la base de datos"""
        self.db_pool = await asyncpg.create_pool(
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            host=os.getenv('DB_HOST')
        )

    async def get_menu_items(self) -> List[Dict[str, Any]]:
        """Obtiene los productos del menú desde la base de datos"""
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT nombre, descripcion, precio_base, es_combo, 
                       categoria, numero_de_piezas
                FROM hatsu.productos
                WHERE activo = true
                ORDER BY categoria, nombre
            """
            rows = await conn.fetch(query)
            new_menu = [dict(row) for row in rows]
            
            # Si el menú cambió, invalidar el caché
            if self._last_menu != new_menu:
                self._last_menu = new_menu
                self.invalidate_prompt_cache()
            
            return new_menu

    async def get_active_locations(self) -> List[Dict[str, Any]]:
        """Obtiene los locales activos desde la base de datos"""
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT nombre, direccion, telefono
                FROM hatsu.locales
                WHERE activo = true
                ORDER BY nombre
            """
            rows = await conn.fetch(query)
            new_locations = [dict(row) for row in rows]
            
            # Si los locales cambiaron, invalidar el caché
            if self._last_locations != new_locations:
                self._last_locations = new_locations
                self.invalidate_prompt_cache()
            
            return new_locations
    
    def set_user_data(self, name=None, email=None, address=None):
        """Establece los datos del usuario"""
        # Guardar datos anteriores para comparar
        old_data = {
            'name': self.user_name,
            'email': self.user_email,
            'address': self.user_address
        }
        
        if name:
            self.user_name = name
        if email:
            self.user_email = email
        if address:
            self.user_address = address
            # Marcar la dirección como confirmada si se establece desde la base de datos
            self.address_confirmed = True
        
        # Si algún dato cambió, invalidar el caché
        new_data = {
            'name': self.user_name,
            'email': self.user_email,
            'address': self.user_address
        }
        if old_data != new_data:
            self.invalidate_prompt_cache()
    
    def get_user_data(self):
        """Obtiene los datos del usuario"""
        return {
            "name": self.user_name,
            "email": self.user_email,
            "address": self.user_address
        }
    
    async def _format_menu_for_prompt(self) -> str:
        """Formatea el menú para el prompt del sistema"""
        try:
            menu_items = await self.get_menu_items()
            if not menu_items:
                return "Error: Menú no disponible"

            # Agrupar items por categoría
            categories = {}
            for item in menu_items:
                cat = item['categoria']
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(item)

            # Formatear el menú
            menu_text = []
            for category, items in categories.items():
                menu_text.append(f"\n{category}")
                for item in items:
                    item_line = [f"- {item['nombre']}"]
                    if item['precio_base']:
                        item_line.append(f" (${int(item['precio_base'])})")
                    if item['descripcion']:
                        item_line.append(f": {item['descripcion']}")
                    if item['numero_de_piezas']:
                        item_line.append(f" ({item['numero_de_piezas']} piezas)")
                    menu_text.append("".join(item_line))

            return "\n".join(menu_text)
        except Exception as e:
            return f"Error al obtener el menú: {str(e)}"

    async def _format_locales_for_prompt(self) -> str:
        """Formatea la información de locales para el prompt del sistema"""
        try:
            locations = await self.get_active_locations()
            if not locations:
                return "Información de locales no disponible"

            locales_text = ["\nNuestros Locales:"]
            for local in locations:
                local_info = []
                local_info.append(f"- {local['nombre']}")
                if local['direccion']:
                    local_info.append(f"\n  Dirección: {local['direccion']}")
                if local['telefono']:
                    local_info.append(f"\n  Teléfono: {local['telefono']}")
                locales_text.append("".join(local_info))

            return "\n".join(locales_text)
        except Exception as e:
            return f"Error al obtener información de locales: {str(e)}"
    
    def _message_needs_schema(self, message: str) -> bool:
        """
        Determina si el mensaje requiere incluir el esquema de la base de datos
        basado en palabras clave relacionadas con pedidos y datos de usuario.
        """
        keywords = [
            '#order', '#user_data', 'confirmar pedido', 'quiero pagar',
            'mi nombre', 'mi dirección', 'mi direccion', 'envialo', 'envíalo',
            'pedido', 'pedir', 'comprar', 'ordenar', 'registrar', 'registrame',
            'regístrame', 'datos', 'información', 'informacion'
        ]
        return any(keyword in message.lower() for keyword in keywords)

    async def process_message(self, message: str, session: AsyncSession = None) -> str:
        """Procesa un mensaje del usuario y retorna la respuesta"""
        try:
            # Si se proporciona una sesión, inicializar datos del usuario
            if session:
                await self.initialize_user_data(session, message, "whatsapp")
            
            # Siempre incluir el menú en el prompt
            include_menu = True
            
            # Determinar si necesitamos incluir el esquema
            include_schema = len(self.conversation_history) == 0 or self._message_needs_schema(message)
            
            # Usar el prompt cacheado correspondiente o generarlo si no existe
            cache_key = (include_menu, include_schema)
            if cache_key not in self.prompt_cache:
                self.prompt_cache[cache_key] = await self._get_system_prompt(
                    include_menu=include_menu,
                    include_schema=include_schema
                )
            system_prompt = self.prompt_cache[cache_key]
            
            # Preparar los mensajes para Claude
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            
            # Agregar historial de conversación
            for msg_pair in self.conversation_history[-5:]:  # Mantener solo los últimos 5 pares
                messages.append({"role": "user", "content": msg_pair[0]})
                messages.append({"role": "assistant", "content": msg_pair[1]})
            
            # Agregar el mensaje actual
            messages.append({"role": "user", "content": message})
            
            try:
                # Generar respuesta
                response = await self.client.messages.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=1000,
                    temperature=0.7
                )
                
                # Guardar en el historial
                self.conversation_history.append((message, response.content[0].text))
                if len(self.conversation_history) > 10:  # Mantener historial limitado
                    self.conversation_history.pop(0)
                
                return response.content[0].text
                
            except Exception as e:
                logger.error(f"Error al procesar mensaje con Claude: {str(e)}")
                return "Lo siento, hubo un error al procesar tu mensaje. Por favor, intenta nuevamente."
                
        except Exception as e:
            logger.error(f"Error general en process_message: {str(e)}")
            return "Lo siento, ocurrió un error inesperado. Por favor, intenta nuevamente."
    
    async def _get_system_prompt(self, include_menu: bool = True, include_schema: bool = False) -> str:
        """Obtiene el prompt del sistema"""
        locales_str = await self._format_locales_for_prompt()
        
        # Obtener el esquema solo si es necesario
        schema_block = ""
        if include_schema:
            schema_str = self._format_schema_for_prompt()
            schema_block = f"\n{schema_str}\n"
        
        # Determinar si el usuario tiene dirección registrada
        has_registered_address = "true" if self.user_address else "false"
        registered_address = self.user_address if self.user_address else "ninguna"
        
        return f"""Eres un asistente virtual de Hatsu Sushi - Vicente Lopez.
        Tu objetivo es ayudar a los clientes a realizar pedidos y responder sus consultas.
        {schema_block}
        Estado actual del usuario:
        - Dirección registrada: {has_registered_address}
        - Dirección: {registered_address}
        
        Información de Locales:
        {locales_str}

        Reglas:
        1. Sé amable y profesional
        2. Habla en español
        3. Si el cliente solicita hablar con un humano, indícalo claramente
        4. Verifica los datos del pedido antes de confirmarlo
        5. Mantén un tono conversacional pero eficiente
        6. Si el cliente pregunta por el menú, muéstralo completo y ordenado
        7. Si el cliente pregunta por locales, proporciona la información detallada
        8. IMPORTANTE: Solo puedes tomar pedidos para el local de Vicente Lopez
        9. IMPORTANTE: Para procesar un pedido:
           a. Confirma los productos y cantidades con el cliente
           b. Pregunta si retira o envío a domicilio
           c. Pregunta método de pago (Efectivo/MercadoPago)
           d. Si tiene dirección registrada, confirma usarla
           e. Si no tiene dirección, solicita los datos
        10. IMPORTANTE: Al generar #ORDER:
            a. Usa el nombre EXACTO del producto del menú
            b. Verifica que el precio coincida con el menú
            c. Calcula correctamente subtotales y total

        Formatos especiales:
        - Pedido: #ORDER:{{"total":1234,"items":[{{"product":"nombre","quantity":1,"precio_unitario":1234,"subtotal":1234}}],"is_takeaway":true/false,"medio_pago":"efectivo/mercadopago"}}
        - Humano: #HUMAN
        - Datos: #USER_DATA:{{"nombre":"Juan","email":"juan@email.com","direccion":"Av. X"}}
        """

    def invalidate_prompt_cache(self):
        """Invalida todas las versiones cacheadas del prompt del sistema"""
        self.prompt_cache.clear()

    async def initialize_user_data(self, session: AsyncSession, phone: str, origen: str = "whatsapp"):
        """Inicializa los datos del usuario desde la base de datos"""
        try:
            # Limpiar el número de teléfono si viene de WhatsApp
            clean_phone = phone.replace("whatsapp:", "")
            
            query = sql_text("""
                SELECT nombre, direccion, email 
                FROM hatsu.usuarios
                WHERE telefono = :phone 
                AND origen = :origen 
                AND (nombre IS NOT NULL OR direccion IS NOT NULL OR email IS NOT NULL)
            """)
            result = await session.execute(query, {"phone": clean_phone, "origen": origen})
            row = result.first()
            
            if row:
                self.user_name = row[0]
                self.user_address = row[1]
                self.user_email = row[2]
                if self.user_address:
                    self.address_confirmed = True
                
                # Invalidar el caché del prompt ya que los datos del usuario cambiaron
                self.invalidate_prompt_cache()
                
            return True
        except Exception as e:
            logger.error(f"Error inicializando datos de usuario: {str(e)}")
            return False

async def main():
    agent = TestAIAgent()
    await agent.init_db()
    print("¡Bienvenido al sistema de prueba de Hatsu Sushi - Vicente Lopez!")
    print("Escribe 'salir' para terminar la conversación.")
    print("-" * 50)
    
    while True:
        user_input = input("\nTú: ")
        if user_input.lower() == 'salir':
            break
        
        try:
            response = await agent.process_message(user_input)
            print("\nAgente:", response)
        except Exception as e:
            print(f"\nError: {str(e)}")
    
    if agent.db_pool:
        await agent.db_pool.close()

if __name__ == "__main__":
    asyncio.run(main()) 
    