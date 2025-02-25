#bling_stock.py
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
from whatsapp_client import create_whatsapp_client, MessageType
import json
from fastapi import FastAPI, Request
import os
from stock_agent import StockAgent
from fastapi import Depends, HTTPException, Header

# Configuração do sistema de logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Classes de configuração usando dataclass para melhor organização
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

# Inicialização do FastAPI para receber webhooks
app = FastAPI()

# Variáveis globais para acesso aos componentes nos endpoints
bling_monitor = None
stock_agent = None

class BlingStockMonitor:
    def __init__(
        self,
        bling_config: BlingConfig,
        whatsapp_config: dict,
        whatsapp_group: WhatsAppGroup
    ):
        """
        Inicializa o monitor de estoque
        :param bling_config: Configurações da API do Bling
        :param whatsapp_config: Configurações do WhatsApp
        :param whatsapp_group: Configurações do grupo do WhatsApp
        """
        self.bling_config = bling_config
        self.whatsapp_client = create_whatsapp_client(**whatsapp_config)
        self.whatsapp_group = whatsapp_group
        self.last_alerts = {}  # Armazena o último alerta enviado para cada produto
        self._last_data = None  # Para armazenar os últimos dados recebidos
        logger.info(f"Monitor de estoque inicializado para o grupo: {self.whatsapp_group.name}")
        logger.info(f"ID do Grupo: {self.whatsapp_group.group_id}")
        
    def format_alert_message(self, alerts: List[Dict]) -> str:
        """
        Formata a mensagem de alerta para envio no WhatsApp com formato melhorado
        :param alerts: Lista de alertas a serem formatados
        :return: Mensagem formatada
        """
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        message = (
            f"🚨 *ALERTA DE ESTOQUE - {current_time}* \n\n"
            f"Produtos com estoque zerado ou negativo:\n"
        )

        # Organiza alertas por depósito
        depositos = {"Depósito Full": [], "Depósito Principal": []}
        for alert in alerts:
            depositos[alert['deposito']].append(alert)

        # Para cada depósito
        for deposito_nome, produtos in depositos.items():
            if not produtos:
                continue
                
            message += f"\n🏪 *{deposito_nome}*\n"
            
            # Crie um mapa de produtos pai -> [variações]
            familias_produtos = {}
            produtos_processados = set()
            
            # Etapa 1: Identificar todos os produtos pai
            pais_encontrados = set()
            for produto in produtos:
                codigo = produto.get('codigo', '')
                nome = produto.get('nome', '')
                
                # Verifica se este produto é pai de algum outro
                for outro_produto in produtos:
                    outro_codigo = outro_produto.get('codigo', '')
                    outro_nome = outro_produto.get('nome', '')
                    
                    # Se outro produto tem o nome deste + algo a mais, este é um pai
                    if (nome and outro_nome and 
                        nome != outro_nome and 
                        nome in outro_nome and
                        len(outro_nome) > len(nome) + 3):
                        pais_encontrados.add(codigo)
                        break
            
            # Etapa 2: Agrupar variações com seus pais
            for pai_codigo in pais_encontrados:
                familias_produtos[pai_codigo] = []
                
                # Encontrar o produto pai nos dados
                pai_produto = None
                for produto in produtos:
                    if produto.get('codigo', '') == pai_codigo:
                        pai_produto = produto
                        produtos_processados.add(pai_codigo)
                        break
                
                # Encontrar todas as variações deste pai
                for produto in produtos:
                    codigo = produto.get('codigo', '')
                    nome = produto.get('nome', '')
                    pai_nome = pai_produto.get('nome', '') if pai_produto else ''
                    
                    # Se não é o próprio pai e contém o nome do pai, é uma variação
                    if (codigo != pai_codigo and pai_nome and 
                        pai_nome in nome and len(nome) > len(pai_nome)):
                        familias_produtos[pai_codigo].append(produto)
                        produtos_processados.add(codigo)
            
            # Etapa 3: Formatar a mensagem com produtos pai e suas variações
            for pai_codigo, variacoes in familias_produtos.items():
                # Encontrar o produto pai
                pai_produto = None
                for produto in produtos:
                    if produto.get('codigo', '') == pai_codigo:
                        pai_produto = produto
                        break
                
                if pai_produto:
                    message += f"\n📦 *{pai_produto.get('nome', '')}*\n(SKU PAI: {pai_produto.get('codigo', 'N/A')})\n\n"
                    
                    if variacoes:
                        message += f"   *Variações com estoque zerado:* ⚠️\n"
                        for i, variacao in enumerate(variacoes, 1):
                            # Extrair apenas a parte da variação
                            nome_completo = variacao.get('nome', '')
                            nome_pai = pai_produto.get('nome', '')
                            nome_variacao = nome_completo.replace(nome_pai, '').strip()
                            
                            # Limpar possíveis separadores no início
                            for sep in [':', ' ', '-', '/', ',']: 
                                if nome_variacao.startswith(sep):
                                    nome_variacao = nome_variacao[1:].strip()
                                    break
                                    
                            message += f"   • {nome_variacao} (SKU: {variacao.get('codigo', 'N/A')})\n"
                    
                    message += "\n"
            
            # Etapa 4: Listar produtos que não são pai nem variações
            for produto in produtos:
                codigo = produto.get('codigo', '')
                if codigo not in produtos_processados:
                    message += f"\n📦 *{produto.get('nome', '')}*\n"
                    message += f"   SKU: {produto.get('codigo', 'N/A')}\n"
                    message += f"   Estoque: {produto.get('estoque_atual', 0)}\n"
                    
        message += (
            "\nℹ️ _Este é um alerta automático do sistema de monitoramento._\n"
            "_Verifique e atualize os estoques conforme necessário._"
        )

        return message

    async def send_group_alert(self, alerts: List[Dict]) -> bool:
        """
        Envia alerta para o grupo do WhatsApp
        :param alerts: Lista de alertas a serem enviados
        :return: True se enviado com sucesso, False caso contrário
        """
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

    async def handle_webhook(self, data: dict, deposito: str):
        try:
            logger.info(f"Webhook recebido para {deposito}")
            
            if 'retorno' not in data or 'estoques' not in data['retorno']:
                logger.warning(f"Formato de dados inválido: campos 'retorno' ou 'estoques' ausentes")
                return {"status": "warning", "message": "Formato de dados inválido"}
            
            estoques_list = data['retorno']['estoques']
            
            # Armazena os dados mais recentes para referência
            self._last_data = data
            
            # Primeiro passo: mapear todos os produtos e identificar relações pai-filho
            produtos_mapeados = {}
            relacoes_pai_filho = {}
            filhos_para_pais = {}
            
            # Mapear todos os produtos
            for produto_wrapper in estoques_list:
                if 'estoque' not in produto_wrapper:
                    continue
                    
                produto = produto_wrapper['estoque']
                codigo = produto.get('codigo', '')
                nome = produto.get('nome', '')
                
                if codigo and nome:
                    produtos_mapeados[codigo] = produto
            
            # Identificar relações pai-filho
            for codigo_filho, produto_filho in produtos_mapeados.items():
                nome_filho = produto_filho.get('nome', '')
                
                for codigo_pai, produto_pai in produtos_mapeados.items():
                    # Pule o mesmo produto
                    if codigo_pai == codigo_filho:
                        continue
                        
                    nome_pai = produto_pai.get('nome', '')
                    
                    # Se o nome do filho contém o nome do pai e é mais longo
                    if (nome_pai and nome_filho and nome_pai in nome_filho and 
                        nome_filho != nome_pai and len(nome_filho) > len(nome_pai) + 3):
                        
                        # Registra relação
                        if codigo_pai not in relacoes_pai_filho:
                            relacoes_pai_filho[codigo_pai] = []
                        
                        relacoes_pai_filho[codigo_pai].append(codigo_filho)
                        filhos_para_pais[codigo_filho] = codigo_pai
                        break
            
            # Segundo passo: verificar estoques e criar alertas
            alerts = []
            processed_codes = set()
            
            for produto_wrapper in estoques_list:
                if 'estoque' not in produto_wrapper:
                    continue
                    
                produto = produto_wrapper['estoque']
                codigo = produto.get('codigo', '')
                nome = produto.get('nome', '')
                
                # Pula se já processamos este código
                if codigo in processed_codes:
                    continue
                    
                estoque_atual = produto.get('estoqueAtual', 0)
                logger.info(f"Processando produto: {nome} ({codigo}) - Estoque total: {estoque_atual}")
                
                # Processa depósitos
                depositos_prod = produto.get('depositos', [])
                for dep_wrapper in depositos_prod:
                    if 'deposito' not in dep_wrapper:
                        continue
                        
                    dep = dep_wrapper['deposito']
                    dep_nome = dep.get('nome', '')
                    dep_saldo = float(dep.get('saldo', 0))
                    dep_desconsiderar = dep.get('desconsiderar', 'N')
                    
                    if dep_desconsiderar == 'S':
                        logger.info(f"Depósito {dep_nome} ignorado (desconsiderar=S)")
                        continue
                    
                    logger.info(f"Produto {codigo} - Depósito: {dep_nome} - Estoque: {dep_saldo}")
                    
                    # Verifica se é um produto pai com variações
                    e_pai_com_variacoes = codigo in relacoes_pai_filho and len(relacoes_pai_filho[codigo]) > 0
                    
                    # Verifica se o produto pai tem pelo menos uma variação com estoque
                    tem_variacao_com_estoque = False
                    if e_pai_com_variacoes:
                        for codigo_filho in relacoes_pai_filho[codigo]:
                            produto_filho = produtos_mapeados.get(codigo_filho)
                            if not produto_filho:
                                continue
                                
                            for dep_filho_wrapper in produto_filho.get('depositos', []):
                                if 'deposito' not in dep_filho_wrapper:
                                    continue
                                    
                                dep_filho = dep_filho_wrapper['deposito']
                                if dep_filho.get('nome') == dep_nome and dep_filho.get('desconsiderar') == 'N':
                                    if float(dep_filho.get('saldo', 0)) > 0:
                                        tem_variacao_com_estoque = True
                                        break
                            
                            if tem_variacao_com_estoque:
                                break
                    
                    # Se é pai com variações e pelo menos uma tem estoque, não alerta sobre o pai
                    if e_pai_com_variacoes and tem_variacao_com_estoque and dep_saldo <= 0:
                        logger.info(f"Produto pai {codigo} ignorado (variações têm estoque)")
                        continue
                    
                    # Se o produto é filho, sempre alerta se estoque <= 0
                    # Se é pai sem variações com estoque, também alerta
                    if dep_saldo <= 0:
                        alert = {
                            'codigo': codigo,
                            'nome': nome,
                            'deposito': deposito,
                            'estoque_atual': dep_saldo,
                            'timestamp': datetime.now()
                        }
                        
                        # Verifica duplicatas no mesmo dia
                        alert_key = f"{codigo}_{deposito}"
                        last_alert = self.last_alerts.get(alert_key)
                        
                        if not last_alert or (datetime.now() - last_alert).days >= 1:
                            alerts.append(alert)
                            self.last_alerts[alert_key] = datetime.now()
                            logger.info(f"Alerta necessário para {codigo} em {deposito}")
                        else:
                            logger.info(f"Alerta ignorado (já enviado hoje) para {codigo} em {deposito}")
                
                processed_codes.add(codigo)
            
            if alerts:
                await self.send_group_alert(alerts)
                logger.info(f"Alerta via webhook processado para {deposito}: {len(alerts)} produtos")
                return {"status": "success", "message": "Alerta enviado", "count": len(alerts)}
            else:
                logger.info(f"Nenhum alerta necessário para {deposito}")
                return {"status": "success", "message": "Nenhum alerta necessário"}
                
        except Exception as e:
            logger.error(f"Erro ao processar webhook para {deposito}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

# Endpoint para verificar o status do servidor
@app.get("/")
async def root():
    """Endpoint raiz para verificar se o servidor está em execução"""
    monitor_status = "Inicializado" if bling_monitor else "Não inicializado"
    agent_status = "Inicializado" if stock_agent else "Não inicializado"
    
    return {
        "status": "online", 
        "monitor": monitor_status,
        "agent": agent_status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# Endpoints para receber webhooks do Bling
@app.post("/full")
async def bling_webhook_full(request: Request):
    """Endpoint para receber webhooks do Bling para o Depósito Full"""
    if not bling_monitor:
        logger.error("Monitor não inicializado")
        return {"status": "error", "message": "Monitor não inicializado"}
    
    try:
        # Verifica o content-type
        content_type = request.headers.get("content-type", "")
        logger.info(f"Content-Type: {content_type}")
        
        if "application/x-www-form-urlencoded" in content_type:
            # Processa form data
            form_data = await request.form()
            json_data = form_data.get("data")
            
            if not json_data:
                logger.warning("Parâmetro 'data' não encontrado no form")
                return {"status": "error", "message": "Parâmetro 'data' não encontrado"}
            
            try:
                data = json.loads(json_data)
                logger.info(f"JSON decodificado com sucesso do parâmetro 'data'")
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar JSON do parâmetro 'data': {e}")
                return {"status": "error", "message": f"JSON inválido no parâmetro 'data': {str(e)}"}
        else:
            # Tenta como JSON padrão
            try:
                data = await request.json()
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar JSON: {e}")
                body = await request.body()
                body_text = body.decode('utf-8', errors='replace')
                logger.info(f"Corpo da requisição bruto: '{body_text}'")
                return {"status": "error", "message": f"JSON inválido: {str(e)}"}
        
        logger.info(f"Dados processados: {json.dumps(data, indent=2)}")
        result = await bling_monitor.handle_webhook(data, "Depósito Full")
        return result
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "message": f"Erro interno: {str(e)}"}

@app.post("/principal")
async def bling_webhook_principal(request: Request):
    """Endpoint para receber webhooks do Bling para o Depósito Principal"""
    if not bling_monitor:
        logger.error("Monitor não inicializado")
        return {"status": "error", "message": "Monitor não inicializado"}
    
    try:
        # Verifica o content-type
        content_type = request.headers.get("content-type", "")
        logger.info(f"Content-Type: {content_type}")
        
        if "application/x-www-form-urlencoded" in content_type:
            # Processa form data
            form_data = await request.form()
            json_data = form_data.get("data")
            
            if not json_data:
                logger.warning("Parâmetro 'data' não encontrado no form")
                return {"status": "error", "message": "Parâmetro 'data' não encontrado"}
            
            try:
                data = json.loads(json_data)
                logger.info(f"JSON decodificado com sucesso do parâmetro 'data'")
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar JSON do parâmetro 'data': {e}")
                return {"status": "error", "message": f"JSON inválido no parâmetro 'data': {str(e)}"}
        else:
            # Tenta como JSON padrão
            try:
                data = await request.json()
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar JSON: {e}")
                body = await request.body()
                body_text = body.decode('utf-8', errors='replace')
                logger.info(f"Corpo da requisição bruto: '{body_text}'")
                return {"status": "error", "message": f"JSON inválido: {str(e)}"}
        
        logger.info(f"Dados processados: {json.dumps(data, indent=2)}")
        result = await bling_monitor.handle_webhook(data, "Depósito Principal")
        return result
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "message": f"Erro interno: {str(e)}"}

# Novo endpoint para processar mensagens do WhatsApp
@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Endpoint para receber mensagens do WhatsApp e processá-las com o agente de estoque
    """
    if not stock_agent:
        logger.warning("Agente de estoque não inicializado. Ignorando mensagem.")
        return {"status": "error", "message": "Agente de estoque não inicializado"}
    
    try:
        # Verifica o content-type
        content_type = request.headers.get("content-type", "")
        logger.info(f"Content-Type: {content_type}")
        
        # Processa a requisição (formato específico da sua API de WhatsApp)
        try:
            if "application/json" in content_type:
                data = await request.json()
            elif "application/x-www-form-urlencoded" in content_type:
                form_data = await request.form()
                json_data = form_data.get("data")
                if json_data:
                    data = json.loads(json_data)
                else:
                    return {"status": "error", "message": "Parâmetro 'data' não encontrado"}
            else:
                body = await request.body()
                data = json.loads(body)
        except Exception as e:
            logger.error(f"Erro ao processar corpo da requisição: {e}")
            return {"status": "error", "message": f"Formato de dados inválido: {str(e)}"}
        
        # Extrai informações da mensagem
        # Exemplo de processamento - ajuste conforme a estrutura da sua API de WhatsApp
        if "messages" in data and len(data["messages"]) > 0:
            message = data["messages"][0]
            
            # Verifica se é uma mensagem de texto
            if message.get("type") == "text":
                sender = message.get("from", "")
                text = message.get("body", "")
                
                # Determina se é um grupo
                is_group = False
                if "chat" in message and message["chat"].get("isGroup", False):
                    is_group = True
                    
                    # Para mensagens de grupo, verifica se mencionou o bot
                    if not any(mention in text.lower() for mention in ["@estoque", "@bot", "@stock"]):
                        logger.info(f"Mensagem de grupo ignorada (sem menção): {text[:30]}...")
                        return {"status": "success", "message": "Mensagem de grupo sem menção ignorada"}
                
                logger.info(f"Mensagem recebida de {sender}: {text[:50]}...")
                
                # Processa a mensagem com o agente
                response = await stock_agent.process_message(sender, text)
                
                if response:
                    # Envia resposta usando o cliente WhatsApp do monitor
                    if bling_monitor and bling_monitor.whatsapp_client:
                        await bling_monitor.whatsapp_client.send_message(
                            text=response,
                            number=sender,
                            message_type=MessageType.TEXT,
                            simulate_typing=True,
                            delay=1000,
                            metadata={"isGroup": is_group}
                        )
                        logger.info(f"Resposta enviada para {sender}")
                    else:
                        logger.error("Monitor não inicializado, não é possível enviar resposta")
                
                return {"status": "success", "message": "Mensagem processada"}
            else:
                logger.info(f"Mensagem ignorada (tipo não suportado): {message.get('type')}")
                return {"status": "success", "message": "Tipo de mensagem não suportado"}
        else:
            logger.info("Requisição sem mensagens")
            return {"status": "success", "message": "Sem mensagens para processar"}
            
    except Exception as e:
        logger.error(f"Erro ao processar webhook do WhatsApp: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "message": f"Erro interno: {str(e)}"}

def initialize_monitor(monitor):
    """Inicializa o monitor global para o webhook"""
    global bling_monitor
    bling_monitor = monitor
    logger.info("Monitor global inicializado com sucesso")

def initialize_stock_agent(agent):
    """Inicializa o agente de estoque global"""
    global stock_agent
    stock_agent = agent
    logger.info("Agente de estoque global inicializado com sucesso")