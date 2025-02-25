import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import re

# Importações do Langchain
from langchain.agents import AgentExecutor, create_openai_functions_agent
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
    
    async def search_product(self, sku: str) -> str:
        """
        Busca um produto pelo SKU na API Bling v3
        """
        try:
            logger.info(f"🔍 Buscando produto com SKU: {sku}")
            url = f"{self.api_url}/produtos"
            params = {"codigo": sku}
            
            async with httpx.AsyncClient() as client:
                logger.info(f"Fazendo requisição para: {url}")
                response = await client.get(
                    url, 
                    headers=self.headers,
                    params=params,
                    timeout=10.0
                )
                
                logger.info(f"Status code: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data") and len(data["data"]) > 0:
                        logger.info(f"✅ Produto encontrado: {data['data'][0].get('nome')}")
                        return data["data"][0]
                    else:
                        logger.warning(f"❌ Produto com SKU {sku} não encontrado")
                        return None
                else:
                    logger.error(f"❌ Erro ao buscar produto: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Erro na busca de produto: {str(e)}")
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

    Para consultas de estoque:
    1. Use o comando "@estoque verificar SKU-123" ou "@bot consultar SKU-123"
    2. O sistema mostrará nome, preço e estoque atual do produto

    Para adicionar estoque:
    1. Use "@estoque adicionar X unidades do SKU-123"
    2. Especifique o depósito se necessário: "@estoque adicionar X SKU-123 depósito principal"

    Para remover estoque:
    1. Use "@estoque remover X unidades do SKU-123"
    2. Especifique o depósito se necessário: "@estoque remover X SKU-123 depósito full"

    Para transferir estoque:
    1. Use "@estoque transferir X unidades do SKU-123 do depósito A para B"

    Regras importantes:
    1. Sempre confirme operações críticas antes de executar
    2. Mostre o estoque atual antes e depois das operações
    3. Peça confirmação para alterações de estoque
    4. Use números inteiros para quantidades
    5. Sempre responda em português"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Configura a memória
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )

        # Configura o agente usando o novo formato
        from langchain.agents import create_openai_functions_agent
        
        agent = create_openai_functions_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )

        # Cria o executor do agente
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=memory,
            handle_parsing_errors=True
        )

        return agent_executor

    async def process_message(self, user_id: str, message: str) -> str:
        """
        Processa uma mensagem recebida de um usuário
        """
        try:
            # Se perguntou sobre comandos disponíveis
            if any(cmd in message.lower() for cmd in ["comandos", "ajuda", "help"]):
                return """🤖 *Comandos Disponíveis*
                    1️⃣ *Consultar Estoque*
    • `@estoque verificar SKU-123`
    • `@bot consultar SKU-123`

    2️⃣ *Adicionar Estoque*
    • `@estoque adicionar 10 unidades do SKU-123`
    • `@estoque add 5 SKU-456 depósito principal`

    3️⃣ *Remover Estoque*
    • `@estoque remover 3 unidades do SKU-789`
    • `@estoque remove 2 SKU-123 depósito full`

    4️⃣ *Transferir Estoque*
    • `@estoque transferir 5 SKU-123 do principal para full`

    📝 *Observações*:
    • Use sempre o SKU correto do produto
    • Especifique a quantidade claramente
    • Mencione o depósito quando necessário
    • Aguarde confirmação em operações críticas

    ❓ Para mais ajuda, use:
    `@bot ajuda [comando]`
    Exemplo: `@bot ajuda transferir`"""

            # Extrai o SKU da mensagem para consulta de estoque
            if "@estoque verificar" in message or "@bot consultar" in message:
                sku_match = re.search(r'(?:verificar|consultar)\s+(\w+)', message)
                if sku_match:
                    sku = sku_match.group(1)
                    # Usa diretamente a ferramenta de busca
                    result = await self.tools[0].run({"sku": sku})
                    
                    # Processa o resultado
                    try:
                        data = json.loads(result)
                        if data.get("found"):
                            product = data["product"]
                            stocks = data.get("stock", [])
                            
                            response = f"📦 *Produto: {product['name']}*\n"
                            response += f"SKU: `{product['sku']}`\n"
                            response += f"Preço: R$ {product['price']}\n\n"
                            response += "*Estoque por Depósito:*\n"
                            
                            for stock in stocks:
                                response += f"- {stock['warehouse_name']}: {stock['quantity']} unidades\n"
                                
                            return response
                        else:
                            return f"❌ Produto com SKU {sku} não encontrado."
                    except json.JSONDecodeError:
                        return "❌ Erro ao processar informações do produto."
                else:
                    return "❌ Por favor, especifique o SKU do produto.\nExemplo: `@estoque verificar SKU123`"

            # Para outros comandos, usa o agente
            result = await self.agent_executor.ainvoke(
                {
                    "input": message
                }
            )
            
            return result.get("output", "Desculpe, não consegui processar sua solicitação.")
            
        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return "❌ Desculpe, ocorreu um erro ao processar sua solicitação. Por favor, tente novamente."
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