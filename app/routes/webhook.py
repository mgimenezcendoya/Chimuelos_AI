from flask import Blueprint, request, Response
import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from ..services.test_agent import TestAIAgent
from ..db.session import AsyncSessionLocal
import requests

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

# Crear una instancia del agente
agent = TestAIAgent()

async def send_whatsapp_message(phone_number: str, message: str) -> bool:
    """
    Envía un mensaje a WhatsApp usando la API de WhatsApp Cloud
    """
    try:
        url = f"https://graph.facebook.com/v17.0/{os.getenv('WHATSAPP_PHONE_ID')}/messages"
        headers = {
            "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": message}
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Mensaje enviado exitosamente a {phone_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error enviando mensaje a WhatsApp: {str(e)}")
        return False

# Inicializar la base de datos
async def init_agent():
    await agent.init_db()

# Ejecutar la inicialización
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(init_agent())

webhook_bp = Blueprint('webhook', __name__)

@webhook_bp.route('/webhook', methods=['GET'])
def verify_webhook():
    """
    Maneja la verificación del webhook de WhatsApp
    """
    # Parámetros que envía Meta para verificación
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    verify_token = os.getenv('WEBHOOK_VERIFY_TOKEN')
    
    logger.info(f"Verificación de webhook - Mode: {mode}, Token: {token}")
    
    # Verificar que los tokens coincidan
    if mode == 'subscribe' and token == verify_token:
        logger.info("Webhook verificado exitosamente")
        return Response(challenge, status=200)
    else:
        logger.error("Verificación de webhook fallida")
        return Response('Error de verificación', status=403)

@webhook_bp.route('/webhook', methods=['POST'])
async def receive_message():
    """
    Maneja los mensajes entrantes de WhatsApp
    """
    try:
        # Obtener el body del mensaje
        data = request.get_json()
        logger.info(f"Mensaje recibido: {data}")
        
        # Verificar si es un mensaje de WhatsApp
        if 'object' in data and data['object'] == 'whatsapp_business_account':
            async with AsyncSessionLocal() as session:
                # Procesar el mensaje
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        if change.get('value', {}).get('messages'):
                            # Obtener el mensaje
                            message = change['value']['messages'][0]
                            
                            if message.get('type') == 'text':
                                # Obtener el número de teléfono del remitente
                                phone_number = message['from']
                                
                                # Procesar solo mensajes de texto
                                text = message['text']['body']
                                response = await agent.process_message(text, session=session)
                                logger.info(f"Respuesta generada: {response}")
                                
                                # Enviar la respuesta de vuelta a WhatsApp
                                await send_whatsapp_message(phone_number, response)
                                
                return Response('OK', status=200)
        
        return Response('Not a WhatsApp message', status=404)
        
    except Exception as e:
        logger.error(f"Error procesando mensaje: {str(e)}")
        return Response(str(e), status=500) 