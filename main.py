# main.py
import logging
import os
from config import load_settings, validate_settings  # Importa do config.py
from bling_stock import BlingStockMonitor, initialize_monitor, app
import uvicorn
import asyncio
from threading import Thread
import time

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('stock_monitor.log')
    ]
)
logger = logging.getLogger(__name__)

async def main():
    # Carrega configurações do .env
    settings = load_settings()
    
    # Depuração dos valores do .env
    print("\n=== Valores das variáveis de ambiente ===")
    print(f"WHATSAPP_GROUP_ID: {os.getenv('WHATSAPP_GROUP_ID', 'Não encontrado')}")
    print(f"WHATSAPP_GROUP_NAME: {os.getenv('WHATSAPP_GROUP_NAME', 'Não encontrado')}")
    print(f"WHATSAPP_INSTANCE: {os.getenv('WHATSAPP_INSTANCE', 'Não encontrado')}")
    print(f"WHATSAPP_API_URL: {os.getenv('WHATSAPP_API_URL', 'Não encontrado')}")
    print(f"WHATSAPP_API_KEY: {os.getenv('WHATSAPP_API_KEY', 'Não encontrado')}")
    print("=======================================\n")
    
    # Valida configurações
    if not validate_settings(settings):
        logger.error("Configurações inválidas. Verifique o arquivo .env")
        return
    
    try:
        logger.info("=== Inicializando Monitor de Estoque via Webhook ===")
        logger.info(f"Grupo WhatsApp: {settings.group.name}")
        logger.info(f"ID do Grupo: {settings.group.group_id}")
        
        # Inicializa o monitor com as configurações
        monitor = BlingStockMonitor(
            bling_config=settings.bling,
            whatsapp_config={
                'api_key': settings.whatsapp.api_key,
                'api_url': settings.whatsapp.api_url,
                'instance': settings.whatsapp.instance
            },
            whatsapp_group=settings.group
        )
        
        # Define o monitor global para o webhook ANTES de iniciar o servidor
        initialize_monitor(monitor)        

        
        # Inicia o servidor webhook
        logger.info("Iniciando servidor para receber webhooks...")
        logger.info("Endpoints disponíveis:")
        logger.info("  - /full: Para atualizações do Depósito Full")
        logger.info("  - /principal: Para atualizações do Depósito Normal")
        logger.info("  - /teste: Para testar o envio de mensagens")
        logger.info("  - /: Para verificar o status do servidor")
        
        # Usar Thread para executar o uvicorn para evitar conflitos de event loop
        server_thread = Thread(target=lambda: uvicorn.run(
            app,
            host="0.0.0.0",
            port=5000,
            log_level="info"
        ))
        server_thread.daemon = True  # Isso permite que o thread seja encerrado quando o programa principal encerrar
        server_thread.start()
        
        # Aguarda um momento para garantir que o servidor inicializou
        logger.info("Aguardando inicialização do servidor...")
        await asyncio.sleep(2)
        logger.info("Servidor inicializado e pronto para receber webhooks!")
        
        # Mantém o programa principal em execução
        while True:
            try:
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                logger.info("Servidor encerrado pelo usuário")
                break
        
    except Exception as e:
        logger.error(f"Erro durante a execução: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Servidor encerrado pelo usuário")