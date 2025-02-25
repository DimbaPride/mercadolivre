# main.py
import logging
import os
from config import load_settings, validate_settings  # Importa do config.py
from bling_stock import BlingStockMonitor, initialize_monitor, app
import uvicorn
import asyncio
from threading import Thread
import time

# Novas importações
from stock_agent import StockAgent  # Novo agente de estoque
from token_manager import BlingTokenManager  # Gerenciador de token
from bling_stock import initialize_stock_agent # Inicializa o agente de estoque

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
    print(f"BLING_CLIENT_ID: {os.getenv('BLING_CLIENT_ID', 'Não encontrado')}")
    print(f"BLING_CLIENT_SECRET: {os.getenv('BLING_CLIENT_SECRET', 'Não encontrado')[0:5]}...")  # Mostra apenas os primeiros 5 caracteres por segurança
    print(f"GROQ_API_KEY: {'Configurado' if os.getenv('GROQ_API_KEY') else 'Não encontrado'}")
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
        agent = await init_stock_agent(settings)
        if agent:
            logger.info("Inicializando agente de estoque global...")
            initialize_stock_agent(agent)
            logger.info("Agente de estoque pronto para processar mensagens")

        
        # Inicia o servidor webhook
        logger.info("Iniciando servidor para receber webhooks...")
        logger.info("Endpoints disponíveis:")
        logger.info("  - /full: Para atualizações do Depósito Full")
        logger.info("  - /principal: Para atualizações do Depósito Normal")
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
        
        # Inicializa o agente de estoque (se configurado)
        agent = await init_stock_agent(settings)
        if agent:
            logger.info("Inicializando agente de estoque global...")
            initialize_stock_agent(agent)
            logger.info("Agente de estoque pronto para processar mensagens")
        
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

async def init_stock_agent(settings):
    """
    Inicializa o agente de estoque com Groq e token manager
    """
    try:
        # Obter credenciais do ambiente
        client_id = os.getenv('BLING_CLIENT_ID', '')
        client_secret = os.getenv('BLING_CLIENT_SECRET', '')
        groq_api_key = os.getenv('GROQ_API_KEY', '')
        
        # Verificar se todas as variáveis de ambiente necessárias existem
        if not client_id or not client_secret:
            logger.warning("BLING_CLIENT_ID ou BLING_CLIENT_SECRET não encontrados. O agente de estoque não será inicializado.")
            return None
            
        if not groq_api_key:
            logger.warning("GROQ_API_KEY não encontrada. O agente de estoque não será inicializado.")
            return None
            
        # Inicializar o gerenciador de token
        logger.info("Inicializando gerenciador de token Bling...")
        token_manager = BlingTokenManager(
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Obter token válido (verificação inicial)
        token = await token_manager.get_valid_token()
        if not token:
            logger.error("Não foi possível obter um token válido para o Bling.")
            return None
            
        # Iniciar job de renovação de token
        token_manager.start_renewal_job(interval_hours=5)
        logger.info("Renovação automática de token configurada (a cada 5 horas)")
            
        # Inicializar o agente de estoque
        logger.info("Inicializando agente de estoque...")
        agent = StockAgent(
            groq_api_key=groq_api_key,
            bling_api_key=token
        )
        
        logger.info("Agente de estoque inicializado com sucesso!")
        return agent
        
    except Exception as e:
        logger.error(f"Erro ao inicializar agente de estoque: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None        

async def init_stock_agent(settings):
    """
    Inicializa o agente de estoque com Groq e token manager
    
    Esta função é independente do monitor de webhook e pode
    ser executada paralelamente.
    """
    try:
        # Obter credenciais do ambiente
        client_id = os.getenv('BLING_CLIENT_ID', '')
        client_secret = os.getenv('BLING_CLIENT_SECRET', '')
        groq_api_key = os.getenv('GROQ_API_KEY', '')
        
        # Verificar se todas as variáveis de ambiente necessárias existem
        if not client_id or not client_secret:
            logger.warning("BLING_CLIENT_ID ou BLING_CLIENT_SECRET não encontrados. O agente de estoque não será inicializado.")
            return None
            
        if not groq_api_key:
            logger.warning("GROQ_API_KEY não encontrada. O agente de estoque não será inicializado.")
            return None
            
        # Inicializar o gerenciador de token
        logger.info("Inicializando gerenciador de token Bling...")
        token_manager = BlingTokenManager(
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Obter token válido (verificação inicial)
        token = await token_manager.get_valid_token()
        if not token:
            logger.error("Não foi possível obter um token válido para o Bling.")
            return None
            
        # Iniciar job de renovação de token
        token_manager.start_renewal_job(interval_hours=5)
        logger.info("Renovação automática de token configurada (a cada 5 horas)")
            
        # Inicializar o agente de estoque
        logger.info("Inicializando agente de estoque...")
        agent = StockAgent(
            groq_api_key=groq_api_key,
            bling_api_key=token
        )
        
        logger.info("Agente de estoque inicializado com sucesso!")
        return agent
        
    except Exception as e:
        logger.error(f"Erro ao inicializar agente de estoque: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Servidor encerrado pelo usuário")