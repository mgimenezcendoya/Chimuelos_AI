import os
import requests
import json
import logging
from dotenv import load_dotenv
from twilio.rest import Client

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

def update_webhook():
    """Actualiza el webhook en Twilio"""
    try:
        # Obtener credenciales
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        
        # Inicializar cliente
        client = Client(account_sid, auth_token)
        
        webhook_url = "https://bc8b-181-2-192-112.ngrok-free.app/webhook"
        logger.info(f"Nueva URL del webhook: {webhook_url}")
        
        # Actualizar la configuración del sandbox usando el cliente de Twilio
        sandbox = client.messaging \
            .v1 \
            .services \
            .update(
                inbound_request_url=webhook_url,
                inbound_method='POST'
            )
        
        logger.info("✅ Webhook actualizado exitosamente")
        logger.info(f"Sandbox configurado con webhook: {sandbox.inbound_request_url}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error actualizando webhook: {str(e)}")
        logger.info("\nPasos para configurar manualmente:")
        logger.info("1. Ve a https://console.twilio.com/")
        logger.info("2. Navega a Messaging -> Try it out -> Send a WhatsApp message")
        logger.info("3. En la sección 'Sandbox Configuration', configura:")
        logger.info(f"   - WHEN A MESSAGE COMES IN: {webhook_url}")
        logger.info("   - METHOD: POST")
        return False

if __name__ == "__main__":
    update_webhook() 