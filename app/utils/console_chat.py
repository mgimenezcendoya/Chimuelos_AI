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
from app.database.database import async_session, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text as sql_text
from app.utils.db_utils import (
    get_menu_from_db, get_locales_from_db, process_order,
    update_user_data, get_user_data, _format_order_confirmation,
    save_message, mark_conversation_for_human, is_in_human_mode
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
        
        # Guardar mensaje de bienvenida
        await save_message(session, usuario_id, welcome_msg, "agente", canal="console")
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
                
                # Guardar mensaje del usuario con intervencion_humana si corresponde
                await save_message(
                    session, 
                    usuario_id, 
                    user_input, 
                    "usuario", 
                    canal="console",
                    intervencion_humana=is_human_request
                )
                await session.commit()
                
                if is_human_request:
                    # Activar intervención humana y mostrar mensaje de transición
                    await mark_conversation_for_human(session, usuario_id, canal="console")
                    human_msg = "Tu mensaje ha sido recibido y será atendido por un operador humano pronto."
                    print("\nBot:", human_msg)
                    await save_message(
                        session,
                        usuario_id,
                        human_msg,
                        "agente",
                        canal="console",
                        intervencion_humana=True
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
                        # Extract the order JSON and clean it up
                        order_json = parts[1].strip()
                        # Remove any trailing text after the JSON object
                        if "}" in order_json:
                            order_json = order_json[:order_json.rindex("}") + 1]
                        # Procesar la orden solo si viene de la consola
                        success, is_new_user, confirmation_message = await process_order(f"#ORDER:{order_json}", session, "console", origen="console")
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
                    
                    # Guardar respuesta del agente
                    await save_message(session, usuario_id, user_message, "agente", canal="console")
                    await session.commit()
                    
                    # Mostrar respuesta
                    print("\nBot:", user_message)
                
            except Exception as e:
                logger.error(f"Error en el chat: {str(e)}")
                error_msg = "Lo siento, ocurrió un error. ¿Podrías intentarlo de nuevo?"
                await save_message(session, usuario_id, error_msg, "agente", canal="console")
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