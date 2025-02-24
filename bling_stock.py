import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
import aiohttp
from typing import List, Dict, Optional
from whatsapp_client import create_whatsapp_client, MessageType

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class BlingConfig:
    """Configuração para API do Bling"""
    api_key: str
    base_url: str = "https://bling.com.br/Api/v2"
    
@dataclass
class WhatsAppGroup:
    """Configuração do grupo do WhatsApp"""
    group_id: str
    name: str

class BlingStockMonitor:
    def __init__(
        self,
        bling_config: BlingConfig,
        whatsapp_config: dict,
        whatsapp_group: WhatsAppGroup
    ):
        self.bling_config = bling_config
        self.whatsapp_client = create_whatsapp_client(**whatsapp_config)
        self.whatsapp_group = whatsapp_group
        self.last_alerts = {}
        
    async def get_stock_levels(self) -> List[Dict]:
        """Busca níveis de estoque no Bling"""
        async with aiohttp.ClientSession() as session:
            url = f"{self.bling_config.base_url}/produtos/json/"
            params = {
                'apikey': self.bling_config.api_key,
                'estoque': 'S'
            }
            
            try:
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return data.get('retorno', {}).get('produtos', [])
            except Exception as e:
                logger.error(f"Erro ao buscar estoque no Bling: {e}")
                return []

    def format_alert_message(self, alerts: List[Dict]) -> str:
        """Formata mensagem de alerta para o grupo"""
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        message = (
            f"🚨 *ALERTA DE ESTOQUE - {current_time}*\n\n"
            f"Produtos com estoque zerado ou negativo:\n\n"
        )

        # Organiza por depósito
        depositos = {"Depósito Full": [], "Depósito Normal": []}
        
        for alert in alerts:
            depositos[alert['deposito']].append(alert)

        # Formata mensagem por depósito
        for deposito_nome, produtos in depositos.items():
            if produtos:
                message += f"*{deposito_nome}*\n"
                for produto in produtos:
                    message += (
                        f"📦 {produto['nome']}\n"
                        f"└ Código: {produto['codigo']}\n"
                        f"└ Estoque: {produto['estoque_atual']}\n\n"
                    )
                message += "\n"

        message += (
            "ℹ️ _Este é um alerta automático do sistema de monitoramento._\n"
            "_Verifique e atualize os estoques conforme necessário._"
        )

        return message

    def check_stock_alerts(self, produtos: List[Dict]) -> List[Dict]:
        """Verifica produtos que precisam de alerta"""
        alerts = []
        
        for produto in produtos:
            produto_data = produto.get('produto', {})
            codigo = produto_data.get('codigo', '')
            nome = produto_data.get('descricao', '')
            
            depositos = produto_data.get('depositos', [])
            for deposito in depositos:
                estoque = float(deposito.get('estoque', 0))
                deposito_id = deposito.get('deposito', {}).get('id')
                deposito_nome = "Depósito Full" if deposito_id == "1" else "Depósito Normal"
                
                if estoque <= 0:
                    alert = {
                        'codigo': codigo,
                        'nome': nome,
                        'deposito': deposito_nome,
                        'estoque_atual': estoque,
                        'timestamp': datetime.now()
                    }
                    
                    # Chave única para evitar duplicatas
                    alert_key = f"{codigo}_{deposito_id}"
                    last_alert = self.last_alerts.get(alert_key)
                    
                    # Só alerta se não houve alerta nas últimas 24h
                    if not last_alert or (datetime.now() - last_alert).days >= 1:
                        alerts.append(alert)
                        self.last_alerts[alert_key] = datetime.now()
        
        return alerts

    async def send_group_alert(self, alerts: List[Dict]) -> bool:
        """Envia alerta para o grupo do WhatsApp"""
        if not alerts:
            return True

        message = self.format_alert_message(alerts)
        
        try:
            success = await self.whatsapp_client.send_message(
                text=message,
                number=self.whatsapp_group.group_id,
                message_type=MessageType.TEXT,
                simulate_typing=True,
                delay=1000,
                metadata={"isGroup": True}
            )
            
            if success:
                logger.info(f"Alerta enviado com sucesso para o grupo: {self.whatsapp_group.name}")
            else:
                logger.error(f"Falha ao enviar alerta para o grupo: {self.whatsapp_group.name}")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta para o grupo: {e}")
            return False

    async def monitor_stock(self, interval_minutes: int = 30):
        """Monitor principal de estoque"""
        logger.info(f"Iniciando monitoramento de estoque para o grupo: {self.whatsapp_group.name}")
        
        while True:
            try:
                logger.info("Verificando níveis de estoque...")
                produtos = await self.get_stock_levels()
                
                alerts = self.check_stock_alerts(produtos)
                if alerts:
                    await self.send_group_alert(alerts)
                
                logger.info(f"Verificação concluída. Próxima em {interval_minutes} minutos.")
                
            except Exception as e:
                logger.error(f"Erro durante monitoramento: {e}")
            
            await asyncio.sleep(interval_minutes * 60)