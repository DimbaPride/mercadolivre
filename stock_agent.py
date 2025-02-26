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
        self.depositos_map = {
            1511573259: "Depósito Principal",
            13801775465: "Depósito Full"
        }  # Mapeamento de ID para nome de depósito   
            
    async def fetch_product_from_api(self, sku: str) -> dict:
        """
        Busca um produto pelo SKU diretamente da API Bling v3
        
        :param sku: SKU do produto a ser buscado
        :return: Dados do produto ou None se não encontrado
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
                
                # Log da resposta completa para depuração
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Estrutura da resposta: {json.dumps(data, indent=2)}")
                    
                    if data.get("data") and len(data["data"]) > 0:
                        logger.info(f"✅ Produto encontrado: {data['data'][0].get('nome')}")
                        return data["data"][0]  # Retorna o primeiro produto encontrado
                    else:
                        logger.warning(f"❌ Produto com SKU {sku} não encontrado")
                        return None
                else:
                    logger.error(f"❌ Erro ao buscar produto: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Erro na busca de produto: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def fetch_product_from_api_by_id(self, product_id: str) -> dict:
        """
        Busca um produto pelo ID diretamente da API Bling v3
        
        :param product_id: ID do produto a ser buscado
        :return: Dados do produto ou None se não encontrado
        """
        try:
            logger.info(f"Buscando produto com ID: {product_id}")
            url = f"{self.api_url}/produtos/{product_id}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, 
                    headers=self.headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("data")
                else:
                    logger.error(f"Erro ao buscar produto por ID: {response.status_code} - {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Erro na busca de produto por ID: {str(e)}")
            return None            

    async def fetch_product_variations(self, parent_id: str) -> list:
        """
        Busca todas as variações de um produto pai
        
        :param parent_id: ID do produto pai
        :return: Lista de variações
        """
        try:
            logger.info(f"Buscando variações do produto com idProdutoPai: {parent_id}")
            url = f"{self.api_url}/produtos"
            params = {"idProdutoPai": parent_id}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, 
                    headers=self.headers,
                    params=params,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    variations = data.get("data", [])
                    logger.info(f"Encontradas {len(variations)} variações para o produto pai ID {parent_id}")
                    return variations
                else:
                    logger.error(f"Erro ao buscar variações: {response.status_code} - {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Erro ao buscar variações: {str(e)}")
            return []
            
    async def fetch_stock_from_api(self, product_id: str) -> dict:
        """
        Obtém o estoque de um produto por ID direto da API Bling
        
        :param product_id: ID interno do produto no Bling
        :return: Dados de estoque do produto
        """
        try:
            # Endpoint correto conforme documentação Bling v3
            url = f"{self.api_url}/estoques/saldos"
            params = {"idsProdutos[]": product_id}
            
            async with httpx.AsyncClient() as client:
                logger.info(f"Consultando estoque para produto ID {product_id}")
                response = await client.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=10.0
                )
                
                logger.info(f"Status code estoque: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Dados de estoque recebidos: {json.dumps(data, indent=2)}")
                    return data
                else:
                    logger.error(f"Erro ao obter estoque: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Erro na consulta de estoque: {str(e)}")
            return None
            
    async def update_stock_in_api(self, product_id: str, warehouse_id: str, operation: str, quantity: float) -> dict:
        """
        Atualiza o estoque de um produto na API do Bling
        
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
    
    async def fetch_warehouses_from_api(self) -> list:
        """
        Obtém a lista de depósitos disponíveis da API do Bling
        
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
                    logger.info(f"Dados de depósitos recebidos: {len(data.get('data', []))} depósitos")
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
            model="llama-3.3-70b-versatile",  # Pode usar outros modelos como "mixtral-8x7b"
            temperature=0.1
        )
        
        # Configura as ferramentas do agente
        self.tools = self._setup_tools()
        
        # Configura o agente
        self.agent_executor = self._setup_agent()
        
        # Estado da conversa (para gerenciar confirmações)
        self.conversation_state = {}
        
    def _setup_tools(self):
        """Configura as ferramentas do agente com nomes descritivos"""
        
        # Ferramenta para buscar produto
        async def tool_search_product(sku: str) -> str:
            """Ferramenta para buscar um produto pelo SKU"""
            # Definir manualmente os depósitos conhecidos
            depots_map = self.bling_tool.depositos_map


            # Buscar o produto pelo SKU
            product_data = await self.bling_tool.fetch_product_from_api(sku)
            
            if not product_data:
                return json.dumps({
                    "found": False, 
                    "message": f"Produto com SKU {sku} não encontrado"
                })
            
            # Verificar se é um produto pai ou filho
            product_id = product_data.get("id")
            is_parent = "idProdutoPai" not in product_data or product_data.get("idProdutoPai") is None
            parent_id = None if is_parent else product_data.get("idProdutoPai")
            
            # Inicializar o objeto de resposta
            result = {
                "found": True,
                "is_parent": is_parent,
                "product": {
                    "id": product_data.get("id"),
                    "name": product_data.get("nome"),
                    "sku": product_data.get("codigo")
                    # Removido preço conforme solicitado
                },
                "stock": []
            }
            
            # Buscar informações de estoque do produto atual
            stock_info = await self.bling_tool.fetch_stock_from_api(product_id)
            
            # Processar estoque do produto atual
            if stock_info and "data" in stock_info:
                for stock_item in stock_info.get("data", []):
                    if str(stock_item.get("produto", {}).get("id")) == str(product_id):
                        result["product"]["total_stock"] = stock_item.get("saldoVirtualTotal", 0)
                        
                        for deposito in stock_item.get("depositos", []):
                            deposito_id = deposito.get("id")
                            deposito_nome = depots_map.get(deposito_id, f"Depósito {deposito_id}")
                            
                            result["stock"].append({
                                "warehouse_id": deposito_id,
                                "warehouse_name": deposito_nome,
                                "quantity": deposito.get("saldoVirtual", 0)
                            })
            
            # Se é um produto pai, buscar suas variações
            if is_parent:
                parent_name = product_data.get("nome", "")
                logger.info(f"Buscando variações para o produto pai: {parent_name}")
                
                # Primeira tentativa: obter o produto pai detalhado que pode conter variações
                url = f"{self.bling_tool.api_url}/produtos/{product_id}"
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url,
                        headers=self.bling_tool.headers,
                        timeout=10.0
                    )
                    
                    variations_data = []
                    
                    if response.status_code == 200:
                        parent_full = response.json().get("data", {})
                        
                        # Verificar se o produto pai já tem variações listadas
                        if "variacoes" in parent_full and parent_full["variacoes"]:
                            logger.info(f"Encontradas {len(parent_full['variacoes'])} variações no produto pai")
                            variations_data = parent_full["variacoes"]
                        else:
                            # Segunda tentativa: buscar variações e filtrar manualmente
                            variations_url = f"{self.bling_tool.api_url}/produtos"
                            params = {
                                "idProdutoPai": product_id,
                                "tipo": "V",  # Apenas variações
                                "limite": 100
                            }
                            
                            variations_response = await client.get(
                                variations_url,
                                headers=self.bling_tool.headers,
                                params=params,
                                timeout=10.0
                            )
                            
                            if variations_response.status_code == 200:
                                all_variations = variations_response.json().get("data", [])
                                logger.info(f"Obtidas {len(all_variations)} variações da API")
                                
                                # Filtro manual: variação deve ter o nome do produto pai como prefixo
                                for var in all_variations:
                                    var_name = var.get("nome", "")
                                    # Verifica se é uma variação real comparando nomes
                                    if var_name.startswith(parent_name):
                                        variations_data.append(var)
                                
                                logger.info(f"Após filtro manual, {len(variations_data)} variações são realmente relacionadas")
                    
                    # Processar apenas as variações relacionadas
                    result["variations"] = []
                    
                    for variation in variations_data:
                        variation_id = variation.get("id")
                        variation_info = {
                            "id": variation_id,
                            "name": variation.get("nome"),
                            "sku": variation.get("codigo"),
                            "stock": []
                        }
                        
                        # Buscar estoque da variação
                        variation_stock = await self.bling_tool.fetch_stock_from_api(variation_id)
                        
                        if variation_stock and "data" in variation_stock:
                            for stock_item in variation_stock.get("data", []):
                                if str(stock_item.get("produto", {}).get("id")) == str(variation_id):
                                    for deposito in stock_item.get("depositos", []):
                                        deposito_id = deposito.get("id")
                                        deposito_nome = depots_map.get(deposito_id, f"Depósito {deposito_id}")
                                        
                                        variation_info["stock"].append({
                                            "warehouse_id": deposito_id,
                                            "warehouse_name": deposito_nome,
                                            "quantity": deposito.get("saldoVirtual", 0)
                                        })
                        
                        result["variations"].append(variation_info)
            
            # Se é um produto filho, buscar apenas informações do pai            
            elif parent_id:
                url = f"{self.bling_tool.api_url}/produtos/{parent_id}"
                
                logger.info(f"Buscando produto pai completo com ID: {parent_id}")
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url,
                        headers=self.bling_tool.headers,
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        parent_data = response.json().get("data")
                        
                        if parent_data:
                            # Informações do pai
                            result["parent"] = {
                                "id": parent_data.get("id"),
                                "name": parent_data.get("nome"),
                                "sku": parent_data.get("codigo")
                            }
                            
                            # Variações já vêm na resposta!
                            if "variacoes" in parent_data and parent_data["variacoes"]:
                                result["siblings"] = []
                                
                                for sibling in parent_data["variacoes"]:
                                    # Não incluir a própria variação
                                    if str(sibling.get("id")) != str(product_id):
                                        result["siblings"].append({
                                            "id": sibling.get("id"),
                                            "name": sibling.get("nome"),
                                            "sku": sibling.get("codigo")
                                        })
            
            return json.dumps(result)

        # Cria a ferramenta estruturada com um nome descritivo
        search_tool = StructuredTool.from_function(
            func=tool_search_product,  # Usa a função com nome descritivo
            name="search_product",  # Nome da ferramenta para o LLM
            description="Busca um produto pelo SKU (código) para verificar se existe e obter informações como nome, preço e estoque atual",
            args_schema=ProductSearchInput
        )
        
        # Ferramenta para atualizar estoque
        async def tool_update_stock(
            sku: str,
            quantity: float,
            operation: str,
            warehouse: str = None,
            target_warehouse: str = None
        ) -> str:
            """
            Ferramenta para atualizar o estoque de um produto
            
            Args:
                sku: Código SKU do produto
                quantity: Quantidade a ser adicionada ou removida
                operation: Operação (adicionar, remover, transferir)
                warehouse: Depósito de origem
                target_warehouse: Depósito de destino (para transferências)
                
            Returns:
                String com resultado da operação
            """
            # Implementação da atualização de estoque...
            try:
                # Primeiro, busca o produto
                product_data = await self.bling_tool.fetch_product_from_api(sku)
                
                if not product_data:
                    return json.dumps({
                        "success": False,
                        "message": f"Produto com SKU {sku} não encontrado"
                    })
                
                # Obter ID do produto
                product_id = product_data.get("id")
                product_name = product_data.get("nome")
                
                # Buscar depósitos
                warehouses = await self.bling_tool.fetch_warehouses_from_api()
                
                # Mapear IDs dos depósitos
                warehouse_id = None
                target_warehouse_id = None
                
                # Encontrar ID do depósito de origem
                if warehouse:
                    for w in warehouses:
                        if warehouse.lower() in w.get("nome", "").lower():
                            warehouse_id = w.get("id")
                            break
                elif warehouses:
                    # Se não especificou depósito, usa o primeiro da lista
                    warehouse_id = warehouses[0].get("id")
                
                # Encontrar ID do depósito de destino para transferências
                if operation == "transferir" and target_warehouse:
                    for w in warehouses:
                        if target_warehouse.lower() in w.get("nome", "").lower():
                            target_warehouse_id = w.get("id")
                            break
                
                # Verificar se encontrou os depósitos
                if not warehouse_id:
                    return json.dumps({
                        "success": False,
                        "message": "Depósito de origem não encontrado"
                    })
                
                if operation == "transferir" and not target_warehouse_id:
                    return json.dumps({
                        "success": False,
                        "message": "Depósito de destino não encontrado"
                    })
                
                # Executar a operação
                result = None
                
                if operation == "adicionar":
                    # Adicionar estoque (Entrada)
                    result = await self.bling_tool.update_stock_in_api(
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        operation="E",  # E = Entrada
                        quantity=abs(quantity)  # Garante que seja positivo
                    )
                    
                elif operation == "remover":
                    # Remover estoque (Saída)
                    result = await self.bling_tool.update_stock_in_api(
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        operation="S",  # S = Saída
                        quantity=abs(quantity)  # Garante que seja positivo
                    )
                    
                elif operation == "transferir":
                    # Transferir = Saída de um depósito + Entrada em outro
                    # 1. Saída do primeiro depósito
                    result_saida = await self.bling_tool.update_stock_in_api(
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        operation="S",
                        quantity=abs(quantity)
                    )
                    
                    # 2. Entrada no segundo depósito
                    result_entrada = await self.bling_tool.update_stock_in_api(
                        product_id=product_id,
                        warehouse_id=target_warehouse_id,
                        operation="E",
                        quantity=abs(quantity)
                    )
                    
                    # Combina os resultados
                    if result_saida.get("success", False) and result_entrada.get("success", False):
                        result = {
                            "success": True,
                            "message": f"Transferência de {quantity} unidades do produto realizada com sucesso"
                        }
                    else:
                        result = {
                            "success": False,
                            "message": "Erro na transferência: " + 
                                      result_saida.get("message", "") + " / " + 
                                      result_entrada.get("message", "")
                        }
                
                # Formata a resposta
                return json.dumps({
                    "success": result.get("success", False),
                    "message": result.get("message", "Operação concluída"),
                    "product": {
                        "id": product_id,
                        "name": product_name,
                        "sku": sku
                    },
                    "operation": operation,
                    "quantity": quantity
                })
                
            except Exception as e:
                logger.error(f"Erro ao atualizar estoque: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return json.dumps({
                    "success": False,
                    "message": f"Erro ao processar operação: {str(e)}"
                })
        
        # Cria a ferramenta estruturada
        update_tool = StructuredTool.from_function(
            func=tool_update_stock,  # Usa a função com nome descritivo
            name="update_stock",  # Nome da ferramenta para o LLM
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
            # Verificar se é uma resposta de confirmação/cancelamento
            if "@confirmar" in message.lower():
                # Verifica se existe uma operação pendente para este usuário
                if user_id in self.conversation_state and "pending_operation" in self.conversation_state[user_id]:
                    # Recupera a operação pendente
                    operation = self.conversation_state[user_id]["pending_operation"]
                    
                    # Verifica se a operação expirou (mais de 5 minutos)
                    if (datetime.now() - operation["timestamp"]).total_seconds() > 300:
                        # Limpa o estado e informa que expirou
                        del self.conversation_state[user_id]
                        return "⏰ A operação expirou. Por favor, inicie novamente."
                    
                    # Executa a operação confirmada
                    update_tool = self.tools[1]  # Ferramenta de atualização
                    
                    # Executa a operação
                    result = await update_tool.run(operation["params"])
                    
                    # Limpa o estado
                    del self.conversation_state[user_id]
                    
                    # Processa o resultado
                    try:
                        data = json.loads(result)
                        if data.get("success"):
                            # Prepara a resposta de sucesso
                            response = f"✅ *Operação realizada com sucesso!*\n\n"
                            response += f"Produto: {operation['product_name']}\n"
                            response += f"SKU: `{operation['sku']}`\n"
                            response += f"Operação: {operation['operation']} {operation['quantity']} unidades\n"
                            
                            # Busca os dados atualizados
                            search_tool = self.tools[0]
                            new_stock_info = await search_tool.run({"sku": operation["sku"]})
                            new_data = json.loads(new_stock_info)
                            
                            # Mostra o estoque atualizado
                            response += "\n*Estoque atualizado:*\n"
                            
                            if new_data.get("found") and new_data.get("stock"):
                                for stock in new_data["stock"]:
                                    warehouse_name = stock.get('warehouse_name', 'Depósito')
                                    quantity = stock.get('quantity', 0)
                                    response += f"- {warehouse_name}: {quantity} unidades\n"
                            
                            return response
                        else:
                            return f"❌ Erro ao executar operação: {data.get('message', 'Erro desconhecido')}"
                    except Exception as e:
                        logger.error(f"Erro ao processar resultado da operação: {str(e)}")
                        return "❌ Erro ao processar resultado da operação."
                    
                else:
                    return "❓ Não há operação pendente para confirmar."
            
            # Verificar se é um cancelamento
            elif "@cancelar" in message.lower():
                if user_id in self.conversation_state and "pending_operation" in self.conversation_state[user_id]:
                    operation = self.conversation_state[user_id]["pending_operation"]
                    operation_type = operation["operation"]
                    product_name = operation["product_name"]
                    
                    # Limpa o estado
                    del self.conversation_state[user_id]
                    
                    return f"🚫 Operação de {operation_type} para produto '{product_name}' cancelada."
                else:
                    return "❓ Não há operação pendente para cancelar."
            
            # Verificar comandos básicos como ajuda ou consulta direta
            elif any(cmd in message.lower() for cmd in ["comandos", "ajuda", "help"]):
                # Retorna a mensagem de ajuda
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
                
            # Consulta direta via regex simples para SKUs
            elif "@estoque verificar" in message or "@bot consultar" in message:
                sku_match = re.search(r'(?:verificar|consultar)\s+([\w\-\.\/\+]+)', message)
                if sku_match:
                    sku = sku_match.group(1)
                    logger.info(f"Consultando SKU: {sku}")
                    
                    # Usa diretamente a ferramenta de busca
                    search_tool = self.tools[0]  # Ferramenta de busca é a primeira na lista
                    result = await search_tool.run({"sku": sku})
                    logger.info(f"Resultado da busca recebido, tamanho: {len(result)} caracteres")
                    
                # Processa o resultado
                    try:                        
                        data = json.loads(result)
                        if data.get("found"):
                            product = data["product"]
                            stocks = data.get("stock", [])
                            
                            response = f"📦 *Produto: {product['name']}*\n"
                            response += f"SKU: `{product['sku']}`\n\n"
                            
                            # Mostrar estoque do produto atual
                            response += "*Estoque por Depósito:*\n"
                            
                            if stocks:
                                for stock in stocks:
                                    warehouse_name = stock.get('warehouse_name', 'Depósito')
                                    quantity = stock.get('quantity', 0)
                                    response += f"- {warehouse_name}: {quantity} unidades\n"
                            else:
                                response += "- Nenhum estoque encontrado para este produto\n"
                            
                            # Mostrar informações do pai se for variação
                            if "parent" in data and data["parent"]:
                                parent = data["parent"]
                                response += f"\n*Produto Pai:* {parent['name']}\n"
                                response += f"SKU do Pai: `{parent['sku']}`\n"
                            
                            # Mostrar variações se for produto pai
                            if "variations" in data and data["variations"]:
                                response += "\n*Variações deste produto:*\n"
                                
                                for i, variation in enumerate(data["variations"], 1):
                                    response += f"{i}. *{variation['name']}*\n"
                                    response += f"   SKU: `{variation['sku']}`\n"
                                    
                                    # Mostrar estoque de cada variação
                                    if "stock" in variation and variation["stock"]:
                                        for stock in variation["stock"]:
                                            warehouse_name = stock.get('warehouse_name', 'Depósito')
                                            quantity = stock.get('quantity', 0)
                                            response += f"   - {warehouse_name}: {quantity} unidades\n"
                                    else:
                                        response += "   - Sem estoque disponível\n"
                            
                            return response
                        else:
                            return f"❌ Produto com SKU {sku} não encontrado."
                    except json.JSONDecodeError as e:
                        logger.error(f"Erro ao decodificar JSON: {e}")
                        logger.error(f"Conteúdo recebido: {result}")
                        return "❌ Erro ao processar informações do produto."
                else:
                    return "❌ Por favor, especifique o SKU do produto.\nExemplo: `@estoque verificar SKU123`"
            
            # PARA TODOS OS OUTROS CASOS: usa o LLM para interpretar
            else:
                logger.info(f"Usando LLM para interpretar: '{message}'")
                # Processar via LLM para interpretar a intenção
                result = await self.agent_executor.ainvoke({"input": message})
                response = result.get("output", "")
                
                if not response:
                    return "Desculpe, não consegui processar sua solicitação."
                
                # Verificar se a resposta indica uma operação de estoque que precisa de confirmação
                if any(op in response.lower() for op in ["adicionar", "remover", "transferir"]) and "estoque" in response.lower():
                    logger.info(f"Possível operação de estoque detectada na resposta: '{response[:100]}...'")
                    # Tentar extrair informações da resposta para criar uma operação pendente
                    try:
                        # Analisar a resposta do LLM para extrair detalhes da operação
                        operation_type = None
                        if "adicionar" in response.lower():
                            operation_type = "adicionar"
                        elif "remover" in response.lower(): 
                            operation_type = "remover"
                        elif "transferir" in response.lower():
                            operation_type = "transferir"
                            
                        # Extrair SKU - podemos usar regex simples aqui
                        sku_match = re.search(r'SKU[:\s]?\s*[`"]?([\w\-\.\/\+]+)[`"]?', response)
                        if not sku_match:  # Tenta outro padrão comum
                            sku_match = re.search(r'código[:\s]?\s*[`"]?([\w\-\.\/\+]+)[`"]?', response, re.IGNORECASE)
                        sku = sku_match.group(1) if sku_match else None
                        
                        # Extrair quantidade
                        qty_match = re.search(r'(\d+)\s*unidades?', response)
                        if not qty_match:  # Tenta outro padrão
                            qty_match = re.search(r'quantidade[:\s]?\s*(\d+)', response, re.IGNORECASE)
                        quantity = int(qty_match.group(1)) if qty_match else 1
                        
                        logger.info(f"Extraído: operação={operation_type}, sku={sku}, quantidade={quantity}")
                        
                        if operation_type and sku:
                            # Buscar informações do produto para confirmar
                            search_tool = self.tools[0]
                            product_data = await search_tool.run({"sku": sku})
                            product_info = json.loads(product_data)
                            
                            if product_info.get("found"):
                                product = product_info["product"]
                                product_name = product.get("name")
                                
                                # Determinar depósitos e parâmetros com base no tipo de operação
                                params = {
                                    "sku": sku,
                                    "quantity": quantity,
                                    "operation": operation_type
                                }
                                
                                # Para transferências, tentar extrair depósitos
                                if operation_type == "transferir":
                                    source_match = re.search(r'de\s+[`"]?([\w\s]+)[`"]?', response, re.IGNORECASE)
                                    target_match = re.search(r'para\s+[`"]?([\w\s]+)[`"]?', response, re.IGNORECASE)
                                    
                                    if source_match and target_match:
                                        params["warehouse"] = source_match.group(1).strip()
                                        params["target_warehouse"] = target_match.group(1).strip()
                                else:
                                    # Para adicionar/remover, extrair depósito
                                    depot_match = re.search(r'depósito\s+[`"]?([\w\s]+)[`"]?', response, re.IGNORECASE)
                                    if depot_match:
                                        params["warehouse"] = depot_match.group(1).strip()
                                
                                logger.info(f"Parâmetros da operação: {params}")
                                
                                # Salvar a operação para confirmação
                                self.conversation_state[user_id] = {
                                    "pending_operation": {
                                        "operation": operation_type,
                                        "sku": sku,
                                        "product_name": product_name,
                                        "quantity": quantity,
                                        "params": params,
                                        "timestamp": datetime.now()
                                    }
                                }
                                
                                # Criar mensagem de confirmação personalizada
                                confirm_msg = f"🔍 *Confirmar operação de estoque:*\n\n"
                                confirm_msg += f"• Operação: {operation_type}\n"
                                confirm_msg += f"• Produto: {product_name}\n"
                                confirm_msg += f"• SKU: `{sku}`\n"
                                confirm_msg += f"• Quantidade: {quantity} unidades\n"
                                
                                # Adicionar informações específicas por operação
                                if operation_type == "transferir":
                                    confirm_msg += f"• De: {params.get('warehouse', 'Depósito padrão')}\n"
                                    confirm_msg += f"• Para: {params.get('target_warehouse', 'Depósito destino')}\n"
                                else:
                                    if "warehouse" in params:
                                        confirm_msg += f"• Depósito: {params['warehouse']}\n"
                                        
                                confirm_msg += f"\n*Para confirmar, responda com \"@confirmar\".*\n"
                                confirm_msg += f"*Para cancelar, responda com \"@cancelar\".*\n"
                                confirm_msg += f"_(Esta operação expira em 5 minutos)_"
                                
                                return confirm_msg
                    except Exception as e:
                        logger.error(f"Erro ao analisar resposta para confirmação: {str(e)}")
                        logger.error(traceback.format_exc())
                        # Se falhar a extração, retorna a resposta original do LLM
                
                # Se não for uma operação que precisa de confirmação, retorna a resposta do LLM
                return response
                
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
    