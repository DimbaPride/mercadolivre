# main.py - com implementação robusta do gerenciador de token
import logging
import os
from config import load_settings, validate_settings  # Importa do config.py
from bling_stock import BlingStockMonitor, initialize_monitor, app, initialize_stock_agent
import uvicorn
import asyncio
from threading import Thread
import time


# Novas importações
from stock_agent import StockAgent  # Novo agente de estoque
from token_manager import BlingTokenManager  # Gerenciador de token melhorado

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
        logger.info(f"Instância WhatsApp: {settings.whatsapp.instance}")
        
        # Configuração do WhatsApp para notificações do token manager
        whatsapp_config = {
            'api_key': settings.whatsapp.api_key,
            'api_url': settings.whatsapp.api_url,
            'instance': settings.whatsapp.instance
        }
        
        # Inicializa o token manager aprimorado com detecção de erros e recuperação
        logger.info("Inicializando gerenciador de token melhorado para o monitor...")
        token_manager = BlingTokenManager(
            client_id=os.getenv('BLING_CLIENT_ID', ''),
            client_secret=os.getenv('BLING_CLIENT_SECRET', ''),
            auth_callback_url=os.getenv('BLING_CALLBACK_URL', ''),
            webhook_url=os.getenv('BLING_WEBHOOK_RECOVERY_URL', ''),
            whatsapp_config=whatsapp_config,
            admin_phone=os.getenv('ADMIN_PHONE', '5516994015075')  # Número para receber alertas
        )
        
        valid_token = await token_manager.get_valid_token()
        
        if valid_token:
            logger.info("Token válido obtido para o monitor")
            # Atualiza o API_KEY nas configurações
            settings.bling.api_key = valid_token
        else:
            logger.warning("Usando token da configuração (pode estar expirado)")
        
        # Inicializa o monitor com as configurações
        monitor = BlingStockMonitor(
            bling_config=settings.bling,
            whatsapp_config={
                'api_key': settings.whatsapp.api_key,
                'api_url': settings.whatsapp.api_url,
                'instance': settings.whatsapp.instance  # Usa o nome da instância
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
        logger.info("  - /whatsapp: Para processar mensagens do WhatsApp")
        logger.info("  - /: Para verificar o status do servidor")
        
        # Usar Thread para executar o uvicorn para evitar conflitos de event loop
        server_thread = Thread(target=lambda: uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="info"
        ))
        server_thread.daemon = True  # Isso permite que o thread seja encerrado quando o programa principal encerrar
        server_thread.start()
        
        # Aguarda um momento para garantir que o servidor inicializou
        logger.info("Aguardando inicialização do servidor...")
        await asyncio.sleep(2)
        logger.info("Servidor inicializado e pronto para receber webhooks!")
        
        # Inicializa o agente de estoque (se configurado)
        agent = await init_stock_agent(settings, token_manager)
        if agent:
            logger.info("Inicializando agente de estoque global...")
            initialize_stock_agent(agent)
            logger.info("Agente de estoque pronto para processar mensagens")
        
        # Inicia o job de renovação de token para garantir que o token sempre esteja válido
        token_manager.start_renewal_job(interval_hours=0.5)
        logger.info("Job de renovação de token iniciado (verificação a cada 1 hora)")
        
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

async def init_stock_agent(settings, token_manager=None):
    """
    Inicializa o agente de estoque com Groq e token manager
    
    Esta função é independente do monitor de webhook e pode
    ser executada paralelamente.
    
    :param settings: Configurações do sistema
    :param token_manager: Token manager já inicializado (opcional)
    :return: Instância do StockAgent ou None
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
        
        # Usar o token manager já inicializado se fornecido, caso contrário criar um novo
        if not token_manager:
            # Inicializar o gerenciador de token
            logger.info("Inicializando gerenciador de token Bling para o agente...")
            token_manager = BlingTokenManager(
                client_id=client_id,
                client_secret=client_secret,
                auth_callback_url=os.getenv('BLING_CALLBACK_URL', ''),
                webhook_url=os.getenv('BLING_WEBHOOK_RECOVERY_URL', ''),
                whatsapp_config={
                    'api_key': settings.whatsapp.api_key,
                    'api_url': settings.whatsapp.api_url,
                    'instance': settings.whatsapp.instance
                },
                admin_phone=os.getenv('ADMIN_PHONE', '5516994015075')  # Número para receber alertas
            )
        
        # Obter token válido (verificação inicial)
        token = await token_manager.get_valid_token()
        if not token:
            logger.error("Não foi possível obter um token válido para o Bling.")
            
            # Tentar renovar forçadamente
            logger.info("Tentando renovar token forçadamente...")
            success = await token_manager.refresh_token()
            
            if success:
                logger.info("Token renovado com sucesso após tentativa forçada.")
                token = await token_manager.get_valid_token()
            else:
                logger.error("Todas as tentativas de obter token válido falharam.")
                return None
            
        # Inicia job de renovação com intervalo mais frequente (a cada 1 hora)
        token_manager.start_renewal_job(interval_hours=1)
        logger.info("Renovação automática de token configurada (a cada 1 hora)")
            
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
    
@app.get("/ping")
def ping():
    return {"message": "pong"}   

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Servidor encerrado pelo usuário")