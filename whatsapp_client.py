# whatsapp_client.py
import logging
import aiohttp
import json
from enum import Enum
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    VIDEO = "video"
    AUDIO = "audio"

class WhatsAppClient:
    def __init__(self, api_key: str, api_url: str, instance: str):
        """
        Cliente para a Evolution API do WhatsApp
        :param api_key: Chave de API da Evolution API
        :param api_url: URL base da Evolution API
        :param instance: Nome ou ID da instância do WhatsApp
        """
        self.api_key = api_key
        self.api_url = api_url
        self.instance = instance
        logger.info(f"Cliente WhatsApp inicializado para instância: {instance}")
    
    async def send_message(self, text: str, number: str, message_type: MessageType = MessageType.TEXT, 
                         simulate_typing: bool = True, delay: int = 1000, 
                         metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Envia uma mensagem via WhatsApp
        :param text: Texto da mensagem
        :param number: Número ou ID do destinatário
        :param message_type: Tipo da mensagem
        :param simulate_typing: Se deve simular digitação
        :param delay: Atraso em milissegundos
        :param metadata: Metadados adicionais
        :return: True se enviado com sucesso, False caso contrário
        """
        try:
            headers = {
                "apikey": self.api_key,
                "Content-Type": "application/json"
            }
            
            # Para mensagens de texto
            if message_type == MessageType.TEXT:
                # Endpoint para envio de mensagens de texto
                endpoint = f"{self.api_url}/message/sendText/{self.instance}"
                
                # Determina se é um grupo com base no número/ID
                is_group = "@g.us" in number
                
                # Ajusta o formato do payload de acordo com as necessidades da API
                payload = {
                    "number": number,
                    "text": text,
                    "isGroup": is_group  # Adiciona isGroup diretamente no payload principal
                }
                
                # Se for grupo, não precisa simular digitação
                if not is_group and simulate_typing:
                    payload["delaySeconds"] = delay // 1000
                
                logger.info(f"Enviando mensagem para: {number} (Grupo: {is_group})")
                logger.info(f"Endpoint: {endpoint}")
                logger.info(f"Payload: {json.dumps(payload, indent=2)}")
                
                # Realiza a requisição HTTP
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        endpoint,
                        headers=headers,
                        json=payload
                    ) as response:
                        status_code = response.status
                        response_text = await response.text()
                        
                        try:
                            response_data = json.loads(response_text)
                            logger.info(f"Resposta completa: {json.dumps(response_data, indent=2)}")
                        except:
                            logger.info(f"Resposta (texto): {response_text}")
                        
                        if status_code == 200 or status_code == 201:
                            logger.info(f"Mensagem enviada com sucesso: {status_code}")
                            return True
                        else:
                            logger.error(f"Erro ao enviar mensagem: {status_code}")
                            return False
            else:
                logger.error(f"Tipo de mensagem não suportado: {message_type}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

def create_whatsapp_client(**kwargs) -> WhatsAppClient:
    """
    Cria uma instância do cliente WhatsApp
    :param kwargs: Parâmetros para o cliente
    :return: Instância do WhatsAppClient
    """
    return WhatsAppClient(
        api_key=kwargs.get('api_key'),
        api_url=kwargs.get('api_url'),
        instance=kwargs.get('instance')
    )