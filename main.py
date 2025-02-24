import asyncio
import logging
from settings import load_settings, validate_settings
from bling_stock_monitor import BlingStockMonitor

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
    
    # Valida configurações
    if not validate_settings(settings):
        logger.error("Configurações inválidas. Verifique o arquivo .env")
        return
    
    try:
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
        
        # Inicia o monitoramento
        await monitor.monitor_stock(interval_minutes=settings.check_interval)
        
    except Exception as e:
        logger.error(f"Erro durante a execução: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Monitoramento encerrado pelo usuário")