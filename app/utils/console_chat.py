import os
import logging
import asyncio
import json
from datetime import datetime
import sys
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
SCHEMA_NAME = os.getenv("SCHEMA_NAME", "hatsu")

# Agregar el directorio raíz al path para poder importar desde app
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from app.services.test_agent import TestAIAgent
from app.database.database import async_session, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text as sql_text
from app.utils.db_utils import (
    get_menu_from_db, get_locales_from_db, process_order,
    update_user_data, get_user_data, _format_order_confirmation,
    save_message, mark_conversation_for_human, is_in_human_mode,
    get_user_session_message_count
)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def initialize_agent():
    """Inicializa el agente con el menú y los locales"""
    await init_db()
    logger.info("Base de datos inicializada")
    
    async with async_session() as session:
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
        # Obtener o crear usuario
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
                "phone": "console",
                "origen": "console"
            }
        )
        usuario_id = result.scalar_one()
        await session.commit()
        
        # Inicializar datos del usuario en el agente
        await agent.initialize_user_data(session, "console", "console")
        
        # Preparar mensaje de bienvenida
        welcome_msg = "¡Bienvenido a Hatsu Sushi - Vicente Lopez!"
        if agent.user_name:
            welcome_msg = f"¡Hola {agent.user_name}! ¡Bienvenido nuevamente!"
        welcome_msg += " Estoy aquí para ayudarte con tu pedido. ¿Qué te gustaría ordenar?"
        
        # Contar tokens del mensaje de bienvenida
        welcome_tokens = agent.estimate_prompt_tokens(welcome_msg)
        
        # Guardar mensaje de bienvenida
        await save_message(
            session=session,
            usuario_id=usuario_id,
            mensaje=welcome_msg,
            rol="agente",
            canal="console",
            tokens=welcome_tokens
        )
        await session.commit()
        print(f"\nBot: {welcome_msg}")
        
        while True:
            try:
                # Obtener input del usuario
                user_input = input("\nTú: ").strip()
                if user_input.lower() == 'salir':
                    print("\n¡Gracias por usar el simulador de chat! 👋")
                    break
                
                # Verificar si el usuario está solicitando intervención humana
                is_human_request = user_input.lower() in ["#human", "hablar con humano", "operador", "ayuda humana"] or "hablar con" in user_input.lower()
                
                # Contar tokens del mensaje del usuario
                prompt_tokens = agent.estimate_prompt_tokens(user_input)
                
                # Guardar mensaje del usuario con intervencion_humana si corresponde
                await save_message(
                    session=session,
                    usuario_id=usuario_id,
                    mensaje=user_input,
                    rol="usuario",
                    canal="console",
                    intervencion_humana=is_human_request,
                    tokens=prompt_tokens
                )
                await session.commit()
                
                # Limitar mensajes por sesión (después de guardar el mensaje)
                count, _ = await get_user_session_message_count(session, usuario_id)
                if count > 1000:
                    limite_msg = "Has excedido el límite de mensajes para esta sesión. Por favor, espera o inicia una nueva sesión más tarde."
                    output_tokens = max(1, len(limite_msg) // 4)
                    await save_message(
                        session=session,
                        usuario_id=usuario_id,
                        mensaje=limite_msg,
                        rol="agente",
                        canal="console",
                        tokens=output_tokens
                    )
                    await session.commit()
                    print("\nBot:", limite_msg)
                    continue
                
                if is_human_request:
                    # Activar intervención humana y mostrar mensaje de transición
                    await mark_conversation_for_human(session, usuario_id, canal="console")
                    human_msg = "Perfecto, en breve una persona de nuestro local continúa esta conversación."
                    print("\nBot:", human_msg)
                    
                    # Contar tokens del mensaje de transición
                    human_tokens = max(1, len(human_msg) // 4)
                    
                    await save_message(
                        session=session,
                        usuario_id=usuario_id,
                        mensaje=human_msg,
                        rol="agente",
                        canal="console",
                        intervencion_humana=True,
                        tokens=human_tokens
                    )
                    await session.commit()
                    continue
                
                # Verificar si está en modo humano antes de procesar con el agente
                is_human_mode = await is_in_human_mode(session, usuario_id)
                if is_human_mode:
                    # Si está en modo humano, solo continuamos sin enviar respuesta
                    continue
                
                # Solo procesar con el agente si NO está en modo humano
                if not is_human_mode:
                    # Procesar mensaje con el agente
                    full_response = await agent.process_message(user_input)
                    
                    # Separar el mensaje para el usuario del JSON técnico
                    user_message = full_response
                    if "#ORDER:" in full_response:
                        parts = full_response.split("#ORDER:")
                        user_message = parts[0].strip()
                        # Extraer el JSON de la orden y limpiarlo
                        order_json = parts[1].strip()
                        if "}" in order_json:
                            order_json = order_json[:order_json.rindex("}") + 1]
                        
                        # Parsear el JSON de la orden para asegurar que tiene todos los campos requeridos
                        order_data = json.loads(order_json)
                        
                        # Procesar la orden solo si viene de la consola
                        success, is_new_user, confirmation_message = await process_order(
                            text=f"#ORDER:{order_json}",
                            session=session,
                            phone="console",
                            origen="console"
                        )
                        if success:
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
                        if await update_user_data(f"#USER_DATA:{user_data}", session, "console", origen="console"):
                            # Recargar los datos del usuario en el agente
                            await agent.initialize_user_data(session, "console", "console")
                    
                    # Contar tokens de la respuesta
                    output_tokens = max(1, len(user_message) // 4)
                    
                    # Guardar respuesta del agente
                    await save_message(
                        session=session,
                        usuario_id=usuario_id,
                        mensaje=user_message,
                        rol="agente",
                        canal="console",
                        tokens=output_tokens
                    )
                    await session.commit()
                    
                    # Mostrar respuesta
                    print("\nBot:", user_message)
                
            except Exception as e:
                logger.error(f"Error en el chat: {str(e)}")
                error_msg = "Lo siento, ocurrió un error. ¿Podrías intentarlo de nuevo?"
                
                # Contar tokens del mensaje de error
                error_tokens = max(1, len(error_msg) // 4)
                
                await save_message(
                    session=session,
                    usuario_id=usuario_id,
                    mensaje=error_msg,
                    rol="agente",
                    canal="console",
                    tokens=error_tokens
                )
                await session.commit()
                print("\nBot:", error_msg)

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