import streamlit as st
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
import asyncio
import json
from datetime import datetime

# Cargar variables de entorno
load_dotenv()

# Configuración de la página
st.set_page_config(
    page_title="Chimuelos SA - Sushi Experience",
    page_icon="🍣",
    layout="centered"
)

# Estilos CSS personalizados
st.markdown("""
<style>
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        display: flex;
        flex-direction: column;
    }
    .user-message {
        background-color: #e6f3ff;
        border-left: 5px solid #2196F3;
    }
    .bot-message {
        background-color: #f0f0f0;
        border-left: 5px solid #ff4b4b;
    }
    .message-content {
        margin-top: 0.5rem;
    }
    .order-details {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

class SushiBot:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    def _get_system_prompt(self) -> str:
        """Obtiene el prompt del sistema"""
        return """Eres un asistente virtual de Chimuelos SA, una moderna franquicia de sushi.
        Tu objetivo es ayudar a los clientes a realizar pedidos y responder sus consultas.
        
        Reglas:
        1. Sé amable y profesional
        2. Habla en español
        3. Si el cliente solicita hablar con un humano, indícalo claramente
        4. Verifica los datos del pedido antes de confirmarlo
        5. Mantén un tono conversacional pero eficiente
        6. Sugiere promociones cuando sea apropiado
        
        Menú disponible:

        ROLLS CLÁSICOS (8 piezas):
        - California Roll ($1200): Kanikama, palta, pepino
        - Philadelphia Roll ($1400): Salmón, queso crema, palta
        - Tuna Roll ($1500): Atún, palta, verdeo
        - Sake Roll ($1400): Salmón, palta, pepino
        
        ROLLS ESPECIALES (8 piezas):
        - Dragon Roll ($2200): Langostinos tempura, palta, salmón por fuera
        - Rainbow Roll ($2000): California roll cubierto de pescados variados
        - Chimuelos Roll ($2400): Langostinos, salmón, queso crema, envuelto en palta
        - Veggie Roll ($1200): Mix de vegetales tempura, palta, queso
        
        COMBOS:
        - Combo Solo ($3500): 24 piezas
          * 8 California Roll
          * 8 Philadelphia Roll
          * 8 Sake Roll
        
        - Combo Pareja ($4800): 32 piezas + 2 bebidas
          * 8 California Roll
          * 8 Philadelphia Roll
          * 8 Dragon Roll
          * 8 Chimuelos Roll
        
        - Combo Familiar ($6500): 48 piezas + 4 bebidas
          * 16 piezas clásicas a elección
          * 24 piezas especiales a elección
          * 8 Nigiri variados
        
        ADICIONALES:
        - Wasabi extra ($200)
        - Jengibre extra ($200)
        - Salsa de soja extra ($150)
        - Palitos ($100)
        
        BEBIDAS:
        - Gaseosas ($500)
        - Agua mineral ($400)
        - Cerveza Kirin ($800)
        - Sake caliente ($1200)
        
        PROMOCIONES ACTUALES:
        - "Happy Hour" (Lunes a Jueves 18-20hs): 20% off en rolls clásicos
        - "All You Can Eat" (Domingos): $8000 por persona
        - "Medio de Semana": 2x1 en rolls clásicos seleccionados (Miércoles)
        - "Combo Ejecutivo": Roll del día + bebida $1800 (Lunes a Viernes 12-16hs)
        
        Formatos de respuesta especiales:
        - Para crear un pedido: #ORDER:{detalles_json}
        - Para derivar a humano: #HUMAN"""
    
    async def get_response(self, messages):
        """Obtiene la respuesta del modelo"""
        response = await self.client.chat.completions.create(
            model=os.getenv("GPT_MODEL", "gpt-4"),
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                *messages
            ],
            temperature=0.7,
            max_tokens=250
        )
        return response.choices[0].message.content

def extract_order(message):
    """Extrae los detalles del pedido del mensaje"""
    if "#ORDER:" in message:
        try:
            json_str = message[message.index("#ORDER:") + 7:].strip()
            # Encontrar el final del JSON
            json_end = json_str.find("\n")
            if json_end != -1:
                json_str = json_str[:json_end]
            return json.loads(json_str)
        except:
            return None
    return None

def initialize_session_state():
    """Inicializa el estado de la sesión"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "orders" not in st.session_state:
        st.session_state.orders = []
    if "bot" not in st.session_state:
        st.session_state.bot = SushiBot()

def display_message(role, content):
    """Muestra un mensaje en el chat"""
    css_class = "user-message" if role == "user" else "bot-message"
    with st.container():
        st.markdown(f"""
        <div class="chat-message {css_class}">
            <div class="message-content">{content}</div>
        </div>
        """, unsafe_allow_html=True)

def display_order(order):
    """Muestra los detalles del pedido"""
    with st.expander("Detalles del Pedido", expanded=True):
        st.write("Items:")
        for item in order["items"]:
            st.write(f"- {item['quantity']}x {item['product']} (${item['price']})")
        st.write(f"Total: ${order['total']}")

async def main():
    initialize_session_state()
    
    # Título y descripción
    st.title("🍣 Chimuelos SA - Sushi Experience")
    st.markdown("### Tu asistente virtual para pedidos de sushi")
    
    # Mostrar el historial de mensajes
    for message in st.session_state.messages:
        display_message(message["role"], message["content"])
        if message["role"] == "assistant":
            order = extract_order(message["content"])
            if order:
                display_order(order)
    
    # Input del usuario
    if prompt := st.chat_input("Escribe tu mensaje aquí..."):
        # Agregar mensaje del usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        display_message("user", prompt)
        
        try:
            # Obtener respuesta del bot
            response = await st.session_state.bot.get_response(st.session_state.messages)
            
            # Agregar respuesta del bot
            st.session_state.messages.append({"role": "assistant", "content": response})
            display_message("assistant", response)
            
            # Extraer y mostrar detalles del pedido si existe
            order = extract_order(response)
            if order:
                display_order(order)
                st.session_state.orders.append({
                    "timestamp": datetime.now().isoformat(),
                    "order": order
                })
        
        except Exception as e:
            st.error(f"Error: {str(e)}")
    
    # Botón para reiniciar la conversación
    if st.button("Reiniciar conversación"):
        st.session_state.messages = []
        st.session_state.orders = []
        st.rerun()

if __name__ == "__main__":
    asyncio.run(main()) 