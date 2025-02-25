import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import re

# Importações do Langchain
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_groq import ChatGroq
from langchain.tools import StructuredTool
from pydantic import BaseModel, Field
from langchain.callbacks.manager import CallbackManagerForToolRun
from langchain.schema import SystemMessage



# Importações para Bling API v3
import httpx
import asyncio

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stock_agent")

class BlingStockTool:
    """Classe base para ferramentas de estoque do Bling v3"""
    
    def __init__(self, api_key: str, api_url: str = "https://api.bling.com.br/v3"):
        """
        Inicializa a ferramenta de estoque
        
        :param api_key: Token de acesso à API Bling v3
        :param api_url: URL base da API Bling v3
        """
        self.api_key = api_key
        self.api_url = api_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def search_product(self, sku: str) -> Dict:
        """
        Busca um produto pelo SKU na API Bling v3
        
        :param sku: Código SKU do produto
        :return: Dados do produto ou None se não encontrado
        """
        try:
            # Endpoint de consulta de produtos com filtro por código
            url = f"{self.api_url}/produtos"
            params = {"codigo": sku}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, 
                    headers=self.headers,
                    params=params,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data") and len(data["data"]) > 0:
                        return data["data"][0]
                    else:
                        logger.warning(f"Produto com SKU {sku} não encontrado")
                        return None
                else:
                    logger.error(f"Erro ao buscar produto: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Erro na busca de produto: {str(e)}")
            return None
    
    async def get_stock(self, product_id: str) -> Dict:
        """
        Obtém o estoque de um produto por ID
        
        :param product_id: ID interno do produto no Bling
        :return: Dados de estoque do produto
        """
        try:
            url = f"{self.api_url}/estoques/produtos/{product_id}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=self.headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Erro ao obter estoque: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Erro na consulta de estoque: {str(e)}")
            return None
    
    async def update_stock(self, product_id: str, warehouse_id: str, operation: str, quantity: float) -> Dict:
        """
        Atualiza o estoque de um produto
        
        :param product_id: ID interno do produto no Bling
        :param warehouse_id: ID do depósito
        :param operation: Tipo de operação (E para entrada, S para saída)
        :param quantity: Quantidade a ser adicionada ou removida
        :return: Resultado da operação
        """
        try:
            url = f"{self.api_url}/estoques/produtos/{product_id}/depositos/{warehouse_id}"
            
            payload = {
                "operacao": operation,  # "E" para entrada, "S" para saída
                "quantidade": quantity,
                "observacoes": f"Operação via Assistente de Estoque em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=10.0
                )
                
                if response.status_code in (200, 201, 204):
                    # Alguns endpoints retornam 204 No Content
                    if response.status_code == 204:
                        return {"success": True, "message": "Estoque atualizado com sucesso"}
                    return response.json()
                else:
                    logger.error(f"Erro ao atualizar estoque: {response.status_code} - {response.text}")
                    return {"success": False, "message": f"Erro: {response.text}"}
                    
        except Exception as e:
            logger.error(f"Erro na atualização de estoque: {str(e)}")
            return {"success": False, "message": f"Erro: {str(e)}"}
    
    async def get_warehouses(self) -> List[Dict]:
        """
        Obtém a lista de depósitos disponíveis
        
        :return: Lista de depósitos
        """
        try:
            url = f"{self.api_url}/depositos"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=self.headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("data", [])
                else:
                    logger.error(f"Erro ao obter depósitos: {response.status_code} - {response.text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Erro na consulta de depósitos: {str(e)}")
            return []


# Classes para definir as entradas e saídas das ferramentas Langchain

class ProductSearchInput(BaseModel):
    """Modelo para busca de produto"""
    sku: str = Field(description="Código SKU do produto a ser buscado")

    class Config:
        """Configuração do modelo Pydantic"""
        arbitrary_types_allowed = True    


class StockUpdateInput(BaseModel):
    """Modelo para atualização de estoque"""
    sku: str = Field(description="Código SKU do produto")
    quantity: float = Field(description="Quantidade a ser adicionada ou removida")
    operation: str = Field(description="Operação: 'adicionar', 'remover' ou 'transferir'")
    warehouse: str | None = Field(None, description="Nome ou ID do depósito")
    target_warehouse: str | None = Field(None, description="Nome ou ID do depósito de destino (para transferências)")

    class Config:
        """Configuração do modelo Pydantic"""
        arbitrary_types_allowed = True


class StockAgent:
    """Agente de gerenciamento de estoque com Langchain e Groq"""
    
    def __init__(self, groq_api_key: str, bling_api_key: str):
        """
        Inicializa o agente de estoque
        
        :param groq_api_key: Chave de API do Groq
        :param bling_api_key: Chave de API do Bling v3
        """
        self.groq_api_key = groq_api_key
        self.bling_tool = BlingStockTool(bling_api_key)
        
        # Inicializa o modelo Groq
        self.llm = ChatGroq(
            api_key=groq_api_key,
            model="llama3-8b-8192",  # Pode usar outros modelos como "mixtral-8x7b"
            temperature=0.1
        )
        
        # Configura as ferramentas do agente
        self.tools = self._setup_tools()
        
        # Configura o agente
        self.agent_executor = self._setup_agent()
        
        # Estado da conversa (para gerenciar confirmações)
        self.conversation_state = {}
        
    def _setup_tools(self):
        """Configura as ferramentas do agente"""
        
        # Ferramenta para buscar produto
        async def search_product(sku: str) -> str:
            """
            Busca um produto pelo SKU
            
            Args:
                sku: Código SKU do produto
                
            Returns:
                String com informações do produto no formato JSON
            """
            result = await self.bling_tool.search_product(sku)
            if not result:
                return json.dumps({
                    "found": False, 
                    "message": f"Produto com SKU {sku} não encontrado"
                })
            
            # Busca informações de estoque
            product_id = result.get("id")
            stock_info = await self.bling_tool.get_stock(product_id)
            
            # Combina informações do produto com estoque
            combined_info = {
                "found": True,
                "product": {
                    "id": result.get("id"),
                    "name": result.get("nome"),
                    "sku": result.get("codigo"),
                    "price": result.get("preco"),
                }
            }
            
            if stock_info and "data" in stock_info:
                combined_info["stock"] = [
                    {
                        "warehouse_id": stock.get("deposito", {}).get("id"),
                        "warehouse_name": stock.get("deposito", {}).get("nome"),
                        "quantity": stock.get("quantidade")
                    }
                    for stock in stock_info.get("data", [])
                ]
            
            return json.dumps(combined_info)
        
        search_tool = StructuredTool.from_function(
            func=search_product,
            name="search_product",
            description="Busca um produto pelo SKU (código) para verificar se existe e obter informações como nome, preço e estoque atual",
            args_schema=ProductSearchInput
        )
        
        # Ferramenta para atualizar estoque
        async def update_stock(
            sku: str,
            quantity: float,
            operation: str,
            warehouse: str = None,
            target_warehouse: str = None
        ) -> str:
            """
            Atualiza o estoque de um produto
            
            Args:
                sku: Código SKU do produto
                quantity: Quantidade a ser adicionada ou removida
                operation: Operação (adicionar, remover, transferir)
                warehouse: Depósito de origem
                target_warehouse: Depósito de destino (para transferências)
                
            Returns:
                String com resultado da operação
            """
            # Implementação existente...
            pass  # Mantenha sua implementação atual
        
        update_tool = StructuredTool.from_function(
            func=update_stock,
            name="update_stock",
            description="Atualiza o estoque de um produto, podendo adicionar, remover ou transferir unidades entre depósitos",
            args_schema=StockUpdateInput
        )
        
        return [search_tool, update_tool]
        
    def _setup_agent(self):
        """Configura o agente com as ferramentas e prompt"""
        
        # Define o template do prompt com todas as variáveis necessárias
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um assistente especializado em gerenciamento de estoque para e-commerce.

    Você tem acesso às seguintes ferramentas:

    {tools}

    Quando receber uma mensagem do usuário:
    1. Identifique a intenção (consulta, adição, remoção ou transferência de estoque)
    2. Extraia o SKU do produto mencionado
    3. Para operações que alteram estoque, confirme com o usuário antes de executar
    4. Pergunte por informações faltantes (como quantidade ou depósito) se necessário
    5. Mostre sempre os detalhes do produto antes de realizar operações

    Para operações de estoque, siga estes passos:
    1. Primeiro, use search_product para verificar se o produto existe e obter suas informações
    2. Mostre ao usuário o nome, SKU e estoque atual do produto para confirmação
    3. Após confirmação, use update_stock para realizar a operação solicitada
    4. Informe o resultado da operação de forma clara

    Ferramentas disponíveis: {tool_names}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Configura a memória do agente
        memory = ConversationBufferMemory(
            return_messages=True,
            memory_key="chat_history"
        )
        
        # Cria o agente usando o prompt com todas as variáveis necessárias
        agent = create_structured_chat_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )
        
        # Cria o executor do agente
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=memory,
            verbose=True,
            handle_parsing_errors=True
        )
        
        return agent_executor
    
    async def process_message(self, user_id: str, message: str) -> str:
        """
        Processa uma mensagem recebida de um usuário
        
        :param user_id: Identificador único do usuário
        :param message: Texto da mensagem
        :return: Resposta a ser enviada ao usuário
        """
        try:
            # Verifica se o usuário está em um fluxo de confirmação
            if user_id in self.conversation_state:
                state = self.conversation_state[user_id]
                
                # Se estiver aguardando confirmação
                if state.get("awaiting_confirmation"):
                    # Verifica se a resposta é uma confirmação
                    if re.search(r'(sim|yes|confirmo|s|y|ok|pode|claro)', message.lower()):
                        # Remove o estado de confirmação
                        operation = state.get("operation")
                        sku = state.get("sku")
                        quantity = state.get("quantity")
                        warehouse = state.get("warehouse")
                        target_warehouse = state.get("target_warehouse")
                        
                        # Executa a operação confirmada
                        result = None
                        
                        if operation and sku and quantity:
                            # Chama a ferramenta de atualização de estoque
                            input_str = f"Execute a operação confirmada: {operation} {quantity} unidades do produto {sku}"
                            if warehouse:
                                input_str += f" no depósito {warehouse}"
                            if target_warehouse:
                                input_str += f" para o depósito {target_warehouse}"
                                
                            # Limpa o estado da conversa
                            del self.conversation_state[user_id]
                            
                            # Executa o agente
                            result = await self.agent_executor.ainvoke({"input": input_str})
                            return result["output"]
                        else:
                            del self.conversation_state[user_id]
                            return "Desculpe, não tenho todas as informações necessárias para completar a operação. Vamos começar de novo."
                    else:
                        # Cancelamento
                        del self.conversation_state[user_id]
                        return "Operação cancelada. Como posso ajudá-lo agora?"
            
            # Detecta se é uma operação que precisa de confirmação
            operation_match = re.search(r'(adicionar|remover|transferir|add|remove)', message.lower())
            sku_match = re.search(r'[a-zA-Z0-9]{3,}[-]?[a-zA-Z0-9]{1,}', message.lower())
            
            if operation_match and sku_match:
                # Executa o agente normalmente para obter informações do produto
                result = await self.agent_executor.ainvoke({"input": message})
                response = result["output"]
                
                # Extrai dados relevantes para confirmação
                operation = operation_match.group(1)
                sku = sku_match.group(0)
                
                # Extrai quantidade mencionada na mensagem
                quantity_match = re.search(r'(\d+)\s*(unidades|peças|itens|und|pcs)?', message.lower())
                quantity = float(quantity_match.group(1)) if quantity_match else None
                
                # Extrai depósito mencionado (se houver)
                warehouse = None
                if "depósito" in message.lower() or "deposito" in message.lower():
                    warehouse_match = re.search(r'dep[óo]sito\s+([a-zA-Z0-9\s]+)', message.lower())
                    if warehouse_match:
                        warehouse = warehouse_match.group(1).strip()
                
                # Extrai depósito de destino para transferências
                target_warehouse = None
                if operation == "transferir" and "para" in message.lower():
                    target_match = re.search(r'para\s+([a-zA-Z0-9\s]+)', message.lower())
                    if target_match:
                        target_warehouse = target_match.group(1).strip()
                
                # Armazena estado para confirmação
                if operation != "verificar" and not "confirmado" in message.lower():
                    self.conversation_state[user_id] = {
                        "awaiting_confirmation": True,
                        "operation": operation,
                        "sku": sku,
                        "quantity": quantity,
                        "warehouse": warehouse,
                        "target_warehouse": target_warehouse,
                        "timestamp": datetime.now()
                    }
                    
                    # Adiciona pergunta de confirmação na resposta
                    if not "?" in response:
                        response += "\n\nVocê confirma esta operação? Responda 'sim' para prosseguir ou 'não' para cancelar."
                
                return response
                
            else:
                # Processamento normal para consultas
                result = await self.agent_executor.ainvoke({"input": message})
                return result["output"]
                
        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {str(e)}")
            return f"Desculpe, ocorreu um erro ao processar sua solicitação: {str(e)}"
    
    def cleanup_expired_states(self, timeout_minutes: int = 15):
        """
        Limpa estados de conversação expirados
        
        :param timeout_minutes: Tempo limite em minutos
        """
        now = datetime.now()
        expired_users = []
        
        for user_id, state in self.conversation_state.items():
            timestamp = state.get("timestamp", now)
            if (now - timestamp) > timedelta(minutes=timeout_minutes):
                expired_users.append(user_id)
        
        for user_id in expired_users:
            del self.conversation_state[user_id]
        
        if expired_users:
            logger.info(f"Limpados {len(expired_users)} estados de conversação expirados")


# Exemplo de como inicializar e usar o agente
if __name__ == "__main__":
    # Carrega variáveis de ambiente
    groq_api_key = os.environ.get("GROQ_API_KEY")
    bling_api_key = os.environ.get("BLING_API_KEY")
    
    # Inicializa o agente
    agent = StockAgent(groq_api_key=groq_api_key, bling_api_key=bling_api_key)