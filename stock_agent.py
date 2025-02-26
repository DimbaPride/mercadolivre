import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import re

# Importações do Langchain
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.agents.output_parsers import OpenAIFunctionsAgentOutputParser
from langchain.agents.format_scratchpad import format_to_openai_functions

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
            # Lista de formatos para tentar (original, maiúsculo, minúsculo)
            sku_variants = [
                sku.strip(),                     # Original sem espaços
                sku.strip().upper(),             # Tudo maiúsculo
                sku.strip().lower(),             # Tudo minúsculo
            ]
            
            logger.info(f"Tentando variantes do SKU: {sku_variants}")
            
            # Tenta cada variante até encontrar um resultado
            for variant in sku_variants:
                url = f"{self.api_url}/produtos"
                params = {"codigo": variant}
                
                async with httpx.AsyncClient() as client:
                    logger.info(f"Fazendo requisição para: {url} com SKU: {variant}")
                    response = await client.get(
                        url, 
                        headers=self.headers,
                        params=params,
                        timeout=10.0
                    )
                    
                    logger.info(f"Status code para variante {variant}: {response.status_code}")
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if data.get("data") and len(data["data"]) > 0:
                            logger.info(f"✅ Produto encontrado com variante {variant}: {data['data'][0].get('nome')}")
                            return data["data"][0]  # Retorna o primeiro produto encontrado
            
            # Se chegou aqui, não encontrou em nenhuma variante
            logger.warning(f"❌ Produto com SKU {sku} não encontrado em nenhuma variante")
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
        :param operation: Tipo de operação (E para entrada, S para saída, B para balanço)
        :param quantity: Quantidade a ser adicionada, removida ou definida (no caso de balanço)
        :return: Resultado da operação
        """
        try:
            # URL do endpoint de estoques
            url = f"{self.api_url}/estoques"
            
            # Construir payload sem modificar a operação recebida
            payload = {
                "produto": {
                    "id": int(product_id)
                },
                "deposito": {
                    "id": int(warehouse_id)
                },
                "operacao": operation,  # Usar exatamente o valor recebido (E, S ou B)
                "quantidade": float(quantity),
                "observacoes": f"Operação via Assistente de Estoque em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            }
            
            logger.info(f"Enviando payload para atualização de estoque: {json.dumps(payload, indent=2)}")
                        
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=10.0
                )
                
                logger.info(f"Status code da atualização: {response.status_code}")
                
                if response.status_code in (200, 201, 204):
                    return {"success": True, "message": "Estoque atualizado com sucesso"}
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
                
                # Usar o mapeamento existente para preencher os nomes dos depósitos
                warehouses_with_names = []
                for w in warehouses:
                    depot_id = w.get("id")
                    # Usar o mapeamento conhecido ao invés dos nomes vazios da API
                    nome = self.bling_tool.depositos_map.get(depot_id, "Depósito Desconhecido")
                    warehouses_with_names.append({"id": depot_id, "nome": nome.lower()})

                logger.info(f"Depósitos disponíveis: {warehouses_with_names}")

                # Código para encontrar o depósito de origem:
                warehouse_id = None
                if warehouse:
                    warehouse_lower = warehouse.lower()
                    for w in warehouses_with_names:
                        nome_deposito = w.get("nome", "").lower()
                        
                        if "principal" in nome_deposito and ("principal" in warehouse_lower or "padrão" in warehouse_lower):
                            warehouse_id = w.get("id")
                            logger.info(f"Depósito PRINCIPAL encontrado: {nome_deposito} (ID: {warehouse_id})")
                            break
                        elif "full" in nome_deposito and "full" in warehouse_lower:
                            warehouse_id = w.get("id")
                            logger.info(f"Depósito FULL encontrado: {nome_deposito} (ID: {warehouse_id})")
                            break

                # Encontrar ID do depósito de destino para transferências - VERSÃO MELHORADA
                target_warehouse_id = None
                if operation == "transferir" and target_warehouse:
                    target_warehouse_lower = target_warehouse.lower()
                    for w in warehouses_with_names:
                        nome_deposito = w.get("nome", "").lower()
                        
                        if "principal" in nome_deposito and ("principal" in target_warehouse_lower or "padrão" in target_warehouse_lower):
                            target_warehouse_id = w.get("id")
                            logger.info(f"Depósito de destino (PRINCIPAL) encontrado: {nome_deposito} (ID: {target_warehouse_id})")
                            break
                        elif "full" in nome_deposito and "full" in target_warehouse_lower:
                            target_warehouse_id = w.get("id")
                            logger.info(f"Depósito de destino (FULL) encontrado: {nome_deposito} (ID: {target_warehouse_id})")
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
                
                elif operation == "balanço":
                    result = await self.bling_tool.update_stock_in_api(
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        operation="B",  # B = Balanço
                        quantity=quantity  # Quantidade total desejada
                    )
                
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
5. Sempre responda em português

Você tem acesso às seguintes ferramentas:
{tools}

Os nomes das ferramentas são: {tool_names}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Configura a memória
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )

        tools_for_agent = self.tools
        agent = (
            {
                "input": lambda x: x["input"],
                "chat_history": lambda x: x.get("chat_history", []),
                "tools": lambda x: [t.metadata for t in tools_for_agent],
                "tool_names": lambda x: ", ".join([t.name for t in tools_for_agent]),
                "agent_scratchpad": lambda x: format_to_openai_functions(x.get("intermediate_steps", []))
            }
            | prompt 
            | self.llm
            | OpenAIFunctionsAgentOutputParser()
        )

        # Cria o executor do agente
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=memory,            
            verbose=True,
            handle_parsing_errors=True
        )

        return agent_executor

    async def process_message(self, user_id: str, message: str) -> str:
        """Processa uma mensagem recebida de um usuário"""
        try:
            # Verificar comandos diretos que não precisam de processamento por IA
            # No método process_message, na parte que processa a confirmação (~linha 765)
            
            # Nesse trecho:
            if "@confirmar" in message.lower():
                # Verifica se existe uma operação pendente para este usuário
                if user_id in self.conversation_state and "pending_operation" in self.conversation_state[user_id]:
                    # Recupera a operação pendente
                    operation = self.conversation_state[user_id]["pending_operation"]
                    
                    # Adicionar este debug:
                    logger.info(f"Operação pendente recuperada: {operation}")
                    
                    # Executa a operação confirmada
                    update_tool = self.tools[1]
                    
                    # Modificar esta linha:
                    # Resultado: await update_tool.run(operation["params"])
                    
                    # Para:
                    params = operation["params"]
                    if not params.get("warehouse") and params.get("operation") != "transferir":
                        # Se não tem depósito especificado, assume o depósito principal (ID 1511573259)
                        params["warehouse"] = "depósito principal"
                        logger.info("Usando depósito principal como padrão para a operação")
                    
                    result = await update_tool.run(params)
                    
                    # Limpa o estado
                    del self.conversation_state[user_id]
                    
                    # Processamento do resultado igual ao código original...
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
            
            elif "@cancelar" in message.lower():
                # Código existente para cancelamento...
                if user_id in self.conversation_state and "pending_operation" in self.conversation_state[user_id]:
                    operation = self.conversation_state[user_id]["pending_operation"]
                    operation_type = operation["operation"]
                    product_name = operation["product_name"]
                    
                    # Limpa o estado
                    del self.conversation_state[user_id]
                    
                    return f"🚫 Operação de {operation_type} para produto '{product_name}' cancelada."
                else:
                    return "❓ Não há operação pendente para cancelar."
            
            elif any(cmd in message.lower() for cmd in ["comandos", "ajuda", "help"]):
                # Retorna a mensagem de ajuda existente              
                
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
                        
                        5️⃣ *Balanço de Estoque*
                        • `@estoque balanço SKU-123 ajustar para 10 unidades`
                        • `@estoque ajustar SKU-456 para 5 unidades no depósito principal`
                
                        📝 *Observações*:
                        • Use sempre o SKU correto do produto
                        • Especifique a quantidade claramente
                        • Mencione o depósito quando necessário
                        • Aguarde confirmação em operações críticas
                
                        ❓ Para mais ajuda, use:
                        `@bot ajuda [comando]`
                        Exemplo: `@bot ajuda transferir`"""
            
            # ABORDAGEM INTELIGENTE BASEADA EM IA - Para qualquer outro comando
            else:
                # ETAPA 1: Usar o LLM para extrair estruturadamente a intenção e parâmetros
                
                extraction_prompt = f"""
                Analise esta mensagem e extraia as informações relevantes para gerenciamento de estoque:
                "{message}"
                
                Responda apenas em formato JSON com as seguintes chaves:
                {{
                    "operation_type": "consultar"|"adicionar"|"remover"|"transferir"|"balanço"|"outro",
                    "sku": "código do produto ou null se não houver",
                    "quantity": número ou null se não aplicável,
                    "source_warehouse": "depósito onde a operação será realizada (ou origem no caso de transferência)",
                    "target_warehouse": "depósito destino (apenas para transferências)",
                    "confidence": número entre 0 e 1 indicando sua confiança nesta interpretação
                }}
                
                Para operações "adicionar", "remover" ou "balanço", o depósito mencionado deve ser extraído como "source_warehouse".
                Para "transferir", extraia o depósito de origem como "source_warehouse" e o destino como "target_warehouse".
                """
                
                logger.info(f"Extraindo parâmetros via LLM para a mensagem: '{message}'")
                
                # Usar o LLM para extrair parâmetros estruturados
                extraction_response = await self.llm.ainvoke([
                    {"role": "system", "content": "Você é um analisador de texto que extrai parâmetros estruturados."},
                    {"role": "user", "content": extraction_prompt}
                ])
                
                # Extrair o JSON da resposta
                try:
                    extracted_text = extraction_response.content
                    logger.info(f"Texto extraído do LLM: {extracted_text[:100]}...")
                    
                    # Verificar se a resposta está vazia
                    if not extracted_text or extracted_text.isspace():
                        logger.warning("Resposta de extração vazia, usando fallback")
                        raise ValueError("Resposta vazia")
                    
                    # Limpar o texto para garantir que temos apenas JSON válido
                    json_text = None
                    
                    # Tentar diferentes formatos comuns
                    if "```json" in extracted_text:
                        # Formato código markdown
                        match = re.search(r'```json\s*(.*?)\s*```', extracted_text, re.DOTALL)
                        if match:
                            json_text = match.group(1)
                    elif "```" in extracted_text:
                        # Outro formato de código sem especificar json
                        match = re.search(r'```\s*(.*?)\s*```', extracted_text, re.DOTALL)
                        if match:
                            json_text = match.group(1)
                    elif "{" in extracted_text and "}" in extracted_text:
                        # JSON sem formatação de código
                        match = re.search(r'\{.*\}', extracted_text, re.DOTALL)
                        if match:
                            json_text = match.group(0)
                    
                    # Se não conseguiu extrair, usar o texto completo
                    if not json_text:
                        json_text = extracted_text.strip()
                    
                    logger.info(f"Tentando processar JSON: {json_text[:100]}...")
                    
                    # Tentar fazer parse do JSON
                    try:
                        params = json.loads(json_text)
                        logger.info(f"Parâmetros extraídos pela IA: {params}")
                    except json.JSONDecodeError:
                        # Se falhar, criar um objeto JSON padrão para indicar baixa confiança
                        logger.warning("Falha ao decodificar JSON, usando objeto padrão")
                        params = {
                            "operation_type": "outro",
                            "sku": None,
                            "quantity": None,
                            "source_warehouse": None,
                            "target_warehouse": None,
                            "confidence": 0.1
                        }
                    
                    # Resto do código continua como antes...
                    
                    # ETAPA 2: Processar com base na intenção identificada
                    operation_type = params.get("operation_type")
                    sku = params.get("sku")
                    
                    # Para consulta de estoque
                    if operation_type == "consultar" and sku:
                        logger.info(f"Consulta de estoque para SKU: {sku}")
                        search_tool = self.tools[0]
                        result = await search_tool.run({"sku": sku})
                        
                        # Processamento igual ao código existente para consultas
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
                                
                                # Mostrar informações do pai e variações se disponíveis
                                # (mantido igual ao código existente)
                                if "parent" in data and data["parent"]:
                                    parent = data["parent"]
                                    response += f"\n*Produto Pai:* {parent['name']}\n"
                                    response += f"SKU do Pai: `{parent['sku']}`\n"
                                
                                if "variations" in data and data["variations"]:
                                    response += "\n*Variações deste produto:*\n"
                                    
                                    for i, variation in enumerate(data["variations"], 1):
                                        response += f"{i}. *{variation['name']}*\n"
                                        response += f"   SKU: `{variation['sku']}`\n"
                                        
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
                        except json.JSONDecodeError:
                            return "❌ Erro ao processar informações do produto."
                    
                    # Para operações que modificam estoque (adicionar, remover, transferir)
                    elif operation_type in ["adicionar", "remover", "transferir", "balanço"] and sku:
                        # Validar o produto antes de preparar a operação
                        search_tool = self.tools[0]
                        product_data = await search_tool.run({"sku": sku})
                        product_info = json.loads(product_data)
                        
                        if not product_info.get("found"):
                            return f"❌ Produto com SKU {sku} não encontrado. Por favor, verifique o código e tente novamente."
                        
                        product = product_info["product"]
                        product_name = product.get("name", "Produto")
                        quantity = params.get("quantity", 1)
                        
                        # Preparar os parâmetros para a operação
                        operation_params = {
                            "sku": sku,
                            "quantity": quantity,
                            "operation": operation_type
                        }
                        
                        # Adicionar informações de depósito quando aplicável
                        if operation_type == "transferir":
                            operation_params["warehouse"] = params.get("source_warehouse")
                            operation_params["target_warehouse"] = params.get("target_warehouse")
                        else:
                            operation_params["warehouse"] = params.get("source_warehouse")
                        
                        logger.info(f"Preparando operação: {operation_params}")
                        
                        # Salvar a operação pendente para confirmação
                        self.conversation_state[user_id] = {
                            "pending_operation": {
                                "operation": operation_type,
                                "sku": sku,
                                "product_name": product_name,
                                "quantity": quantity,
                                "params": operation_params,
                                "timestamp": datetime.now()
                            }
                        }
                        
                        # Preparar a mensagem de confirmação
                        # Criar mensagem de confirmação personalizada
                        confirm_msg = f"🔍 *Confirmar operação de estoque:*\n\n"
                        confirm_msg += f"• Operação: {operation_type}\n"
                        confirm_msg += f"• Produto: {product_name}\n"
                        confirm_msg += f"• SKU: `{sku}`\n"
                        confirm_msg += f"• Quantidade: {quantity} unidades\n"
                        
                        # Adicionar informações específicas por operação
                        if operation_type == "transferir":
                            source = params.get("source_warehouse", "Depósito padrão")
                            target = params.get("target_warehouse", "Depósito destino")
                            confirm_msg += f"• De: {source}\n"
                            confirm_msg += f"• Para: {target}\n"
                        else:
                            warehouse = params.get("source_warehouse")
                            if warehouse:
                                confirm_msg += f"• Depósito: {warehouse}\n"
                        
                        # Adicionar estoque atual para contexto do usuário
                        confirm_msg += "\n*Estoque atual:*\n"
                        for stock in product_info.get("stock", []):
                            warehouse_name = stock.get('warehouse_name', 'Depósito')
                            current_qty = stock.get('quantity', 0)
                            confirm_msg += f"- {warehouse_name}: {current_qty} unidades\n"
                                
                        confirm_msg += f"\n*Para confirmar, responda com \"@confirmar\".*\n"
                        confirm_msg += f"*Para cancelar, responda com \"@cancelar\".*\n"
                        confirm_msg += f"_(Esta operação expira em 5 minutos)_"
                        
                        return confirm_msg
                    
                    # Para outros casos ou se a IA não identificou corretamente
                    else:
                        # Confiança baixa ou operação desconhecida, processar via LLM genérico
                        if params.get("confidence", 0) < 0.7 or operation_type == "outro":
                            logger.info(f"Baixa confiança ou tipo desconhecido, usando LLM genérico")
                            result = await self.agent_executor.ainvoke({"input": message})
                            return result.get("output", "Desculpe, não consegui processar sua solicitação.")
                        else:
                            return "❓ Não consegui entender o que você deseja fazer com o estoque. Por favor, tente novamente com um comando mais claro."
                    
                except Exception as e:
                    logger.error(f"Erro ao processar extração: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    
                    # Fallback para o processamento original
                    logger.info(f"Usando LLM padrão como fallback")
                    result = await self.agent_executor.ainvoke({"input": message})
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
