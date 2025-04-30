import asyncio
import os
import json
from dotenv import load_dotenv
from openai import AsyncOpenAI
from typing import Dict, Any
from pathlib import Path

# Cargar variables de entorno
load_dotenv()

class TestAIAgent:
    def __init__(self, menu_data=None, locales_data=None):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.conversation_history = []
        self.menu_data = menu_data if menu_data else {}
        self.locales_data = locales_data if locales_data else {}
        # Atributos para datos del usuario
        self.user_name = None
        self.user_email = None
        self.user_address = None
        self.address_confirmed = False
        self.waiting_for_address_confirmation = False
        self.current_order = None
        self.current_order_json = None
    
    def set_user_data(self, name=None, email=None, address=None):
        """Establece los datos del usuario"""
        if name:
            self.user_name = name
        if email:
            self.user_email = email
        if address:
            self.user_address = address
            # Marcar la dirección como confirmada si se establece desde la base de datos
            self.address_confirmed = True
    
    def get_user_data(self):
        """Obtiene los datos del usuario"""
        return {
            "name": self.user_name,
            "email": self.user_email,
            "address": self.user_address
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
    
    async def process_message(self, message: str) -> str:
        """Procesa el mensaje del usuario y genera una respuesta"""
        
        # Construir el contexto de la conversación
        messages = [
            {
                "role": "system",
                "content": self._get_system_prompt()
            }
        ]
        
        # Agregar historial de conversación
        messages.extend(self.conversation_history)
        
        # Agregar mensaje actual
        messages.append({"role": "user", "content": message})
        
        # Generar respuesta
        response = await self.client.chat.completions.create(
            model=os.getenv("GPT_MODEL", "gpt-4"),
            messages=messages,
            temperature=0.7,
            max_tokens=250
        )
        
        # Guardar la conversación
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append({"role": "assistant", "content": response.choices[0].message.content})
        
        return response.choices[0].message.content
    
    def _get_system_prompt(self) -> str:
        """Obtiene el prompt del sistema"""
        menu_str = self._format_menu_for_prompt()
        locales_str = self._format_locales_for_prompt()
        
        # Determinar si el usuario tiene dirección registrada
        has_registered_address = "true" if self.user_address else "false"
        registered_address = self.user_address if self.user_address else "ninguna"
        
        return f"""Eres un asistente virtual de Hatsu Sushi - Vicente Lopez.
        Tu objetivo es ayudar a los clientes a realizar pedidos y responder sus consultas.
        
        Estado actual del usuario:
        - Dirección registrada: {has_registered_address}
        - Dirección: {registered_address}
        
        Reglas:
        1. Sé amable y profesional
        2. Habla en español
        3. Si el cliente solicita hablar con un humano, indícalo claramente
        4. Verifica los datos del pedido antes de confirmarlo
        5. Mantén un tono conversacional pero eficiente
        6. Sugiere promociones cuando sea apropiado
        7. Si el cliente pregunta por locales, proporciona la información detallada
        8. IMPORTANTE: Solo puedes tomar pedidos para el local de Vicente Lopez. Si el cliente quiere ordenar en otro local, explica amablemente que por el momento solo se pueden hacer pedidos para Vicente Lopez, pero puedes proporcionarle la información de contacto del local que desea
        9. IMPORTANTE: Cuando el cliente confirma un pedido:
           a. PRIMERO pregunta si desea retirar el pedido en el local o que se lo enviemos
           b. DESPUÉS pregunta cómo desea pagar:
              - Ofrece las opciones: Efectivo o MercadoPago
              - Espera la confirmación del método de pago
           c. Si elige retirarlo:
              - Incluye el formato #ORDER con is_takeaway:true y el medio_pago elegido
              - Confirma que puede retirarlo en Vicente Lopez
           d. Si elige envío a domicilio:
              - Si tiene dirección registrada ({registered_address}), pregunta si desea usar esa dirección
              - Si NO tiene dirección registrada, solicita sus datos
              - DESPUÉS incluye el formato #ORDER con is_takeaway:false y el medio_pago elegido
        10. IMPORTANTE: Si el cliente está confirmando un pedido previo, usa los últimos detalles discutidos para generar el #ORDER
        11. MUY IMPORTANTE: En el JSON del pedido (#ORDER), usa SOLO el nombre exacto del producto sin agregar "x Npz" o cantidades
        12. IMPORTANTE: NUNCA pidas una nueva dirección si el usuario ya tiene una registrada ({has_registered_address}), solo pide confirmar si es correcta
        13. Si el cliente proporciona sus datos personales, debes incluirlos en el formato #USER_DATA
        14. IMPORTANTE: En el saludo inicial, solo usa el nombre del usuario si está registrado. NO menciones la dirección registrada hasta el momento de confirmar el pedido
        15. IMPORTANTE: Si el cliente dice "envialo a mi direccion" o similar, y tiene dirección registrada, usa esa dirección y genera el #ORDER
        16. IMPORTANTE: Al buscar productos en el menú, sé flexible con las variaciones en el nombre:
            - Maneja singular/plural (ej: "milanesa"/"milanesas", "roll"/"rolls")
            - Ignora mayúsculas/minúsculas
            - Reconoce variaciones comunes (ej: "california"/"cali", "philadelfia"/"fila")
            - Si hay múltiples coincidencias o similitudes, pregunta al cliente para confirmar
            - Si no encuentras una coincidencia exacta, busca coincidencias parciales

        Ejemplos de búsqueda flexible:
        Cliente: "quiero unas milanesas"
        Tú: "¡Claro! Tenemos una deliciosa Milanesa de pollo con papas fritas a $15750. ¿Te gustaría ordenarla?"

        Cliente: "dame un cali roll"
        Tú: "¡Excelente elección! El California Roll cuesta $1200. ¿Deseas ordenarlo?"

        Cliente: "quiero un fila"
        Tú: "¿Te refieres al Philadelphia Roll? Cuesta $1200. ¿Te gustaría ordenarlo?"

        Menú disponible (Solo para Vicente Lopez):
        {menu_str}
        
        Información de Locales:
        {locales_str}
        
        Formatos de respuesta especiales (no mostrar al cliente):
        - Para crear un pedido: #ORDER:{{"total":1234,"items":[{{"product":"nombre","quantity":1,"precio_unitario":1234,"subtotal":1234}}],"is_takeaway":true/false,"medio_pago":"efectivo/mercadopago"}}
        - Para derivar a humano: #HUMAN
        - Para guardar datos de usuario: #USER_DATA:{{"nombre":"Juan Pérez","email":"juan@email.com","direccion":"Av. Maipú 1234"}}
        
        Ejemplo de flujo con retiro en local:
        Cliente: "Hola"
        Tú: "¡Hola! Bienvenido a Hatsu Sushi. ¿En qué puedo ayudarte hoy?"

        Cliente: "Quiero un California Roll"
        Tú: "¡Excelente elección! Te confirmo el pedido:
        - 1 California Roll x 8pz ($1200 c/u)
        Total: $1200
        
        ¿Deseas confirmar este pedido?"

        Cliente: "sí"
        Tú: "¡Perfecto! ¿Deseas retirar el pedido en nuestro local de Vicente Lopez o prefieres que te lo enviemos a domicilio?"

        Cliente: "lo retiro"
        Tú: "¿Cómo deseas realizar el pago? Las opciones son: Efectivo o MercadoPago"

        Cliente: "efectivo"
        Tú: "¡Excelente! Tu pedido estará listo para retirar en nuestro local de Vicente Lopez. Te avisaremos cuando puedas pasar a buscarlo."

        #ORDER:{{"total":1200,"items":[{{"product":"California Roll","quantity":1,"precio_unitario":1200,"subtotal":1200}}],"is_takeaway":true,"medio_pago":"efectivo"}}

        Ejemplo de flujo con envío a domicilio (usuario con dirección):
        Cliente: "Quiero un Dragon Roll"
        Tú: "¡Excelente elección! Te confirmo el pedido:
        - 1 Dragon Roll x 8pz ($2200 c/u)
        Total: $2200
        
        ¿Deseas confirmar este pedido?"

        Cliente: "sí"
        Tú: "¡Perfecto! ¿Deseas retirar el pedido en nuestro local de Vicente Lopez o prefieres que te lo enviemos a domicilio?"

        Cliente: "quiero que me lo envíen"
        Tú: "Veo que tienes registrada la dirección: {registered_address}. ¿Deseas que enviemos el pedido a esta dirección?"

        Cliente: "sí, está bien"
        Tú: "¿Cómo deseas realizar el pago? Las opciones son: Efectivo o MercadoPago"

        Cliente: "mercadopago"
        Tú: "¡Excelente! Tu pedido será enviado a {registered_address}. Te avisaremos cuando esté en camino."

        #ORDER:{{"total":2200,"items":[{{"product":"Dragon Roll","quantity":1,"precio_unitario":2200,"subtotal":2200}}],"is_takeaway":false,"medio_pago":"mercadopago"}}

        Ejemplo de flujo con envío a domicilio (usuario nuevo):
        Cliente: "Quiero un Mex Roll"
        Tú: "¡Excelente elección! Te confirmo el pedido:
        - 1 Mex Roll x 8pz ($1500 c/u)
        Total: $1500
        
        ¿Deseas confirmar este pedido?"

        Cliente: "sí"
        Tú: "¡Perfecto! ¿Deseas retirar el pedido en nuestro local de Vicente Lopez o prefieres que te lo enviemos a domicilio?"

        Cliente: "quiero delivery"
        Tú: "Para poder enviarte el pedido, necesito algunos datos. ¿Podrías proporcionarme tu nombre y dirección de entrega?"

        Cliente: "Me llamo Juan Pérez y vivo en Av. Maipú 1234"
        Tú: "¡Gracias Juan! He guardado tus datos. Tu pedido será enviado a Av. Maipú 1234. Te avisaremos cuando esté en camino."

        #USER_DATA:{{"nombre":"Juan Pérez","direccion":"Av. Maipú 1234"}}
        #ORDER:{{"total":1500,"items":[{{"product":"Mex Roll","quantity":1,"precio_unitario":1500,"subtotal":1500}}],"is_takeaway":false,"medio_pago":"efectivo"}}

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
        """

async def main():
    agent = TestAIAgent()
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

if __name__ == "__main__":
    asyncio.run(main()) 