import json
import os
import time
import logging
import asyncio
import threading
from datetime import datetime, timedelta
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bling_token_manager")

class BlingTokenManager:
    """
    Gerenciador de token para API Bling v3
    - Gerencia renovação automática de tokens
    - Verifica validade de tokens antes de requisições
    - Inicializa um job em background para renovação periódica
    """
    
    def __init__(self, client_id, client_secret, token_file="bling_token.json", env_file=".env"):
        """
        Inicializa o gerenciador de tokens
        
        :param client_id: Client ID do aplicativo Bling
        :param client_secret: Client Secret do aplicativo Bling
        :param token_file: Arquivo para armazenar os dados do token
        :param env_file: Arquivo .env para atualizar a variável BLING_API_KEY
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.env_file = env_file
        self.token_url = "https://www.bling.com.br/Api/v3/oauth/token"
        
        # Dados do token em memória
        self._token_data = None
        self._token_lock = threading.Lock()
        
        # Carrega token do arquivo, se existir
        self._load_token()
        
        # Flag para controlar o job de renovação
        self._renewal_running = False
        self._renewal_task = None
        
        logger.info("Gerenciador de token Bling inicializado")
    
    def _load_token(self):
        """Carrega os dados do token do arquivo"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as file:
                    self._token_data = json.load(file)
                logger.info("Token carregado do arquivo")
                
                # Verifica se o token tem campo created_at (para compatibilidade com versão anterior)
                if self._token_data and "created_at" not in self._token_data:
                    logger.warning("Token carregado não tem campo created_at, adicionando timestamp atual")
                    self._token_data["created_at"] = datetime.now().timestamp()
                    self._save_token()
            else:
                logger.warning(f"Arquivo de token {self.token_file} não encontrado")
        except Exception as e:
            logger.error(f"Erro ao carregar token: {str(e)}")
    
    def _save_token(self):
        """Salva os dados do token no arquivo"""
        try:
            with self._token_lock:
                with open(self.token_file, "w") as file:
                    json.dump(self._token_data, file, indent=2)
                
                # Atualiza o arquivo .env
                self._update_env_file()
                
            logger.info("Token salvo no arquivo")
        except Exception as e:
            logger.error(f"Erro ao salvar token: {str(e)}")
    
    def _update_env_file(self):
        """Atualiza a variável BLING_API_KEY no arquivo .env"""
        try:
            if not self._token_data or "access_token" not in self._token_data:
                return
            
            access_token = self._token_data["access_token"]
            
            # Se o arquivo .env não existir, cria
            if not os.path.exists(self.env_file):
                with open(self.env_file, "w") as env_file:
                    env_file.write(f"BLING_API_KEY={access_token}\n")
                return
            
            # Lê o arquivo .env
            with open(self.env_file, "r") as env_file:
                lines = env_file.readlines()
            
            # Verifica se a variável já existe
            bling_api_key_exists = False
            updated_lines = []
            
            for line in lines:
                if line.startswith("BLING_API_KEY="):
                    updated_lines.append(f"BLING_API_KEY={access_token}\n")
                    bling_api_key_exists = True
                else:
                    updated_lines.append(line)
            
            # Se a variável não existir, adiciona
            if not bling_api_key_exists:
                updated_lines.append(f"BLING_API_KEY={access_token}\n")
            
            # Escreve o arquivo atualizado
            with open(self.env_file, "w") as env_file:
                env_file.writelines(updated_lines)
            
            # Também atualiza a variável de ambiente atual
            os.environ["BLING_API_KEY"] = access_token
            
            logger.info("Arquivo .env atualizado com o novo token")
        except Exception as e:
            logger.error(f"Erro ao atualizar arquivo .env: {str(e)}")
    
    async def refresh_token(self):
        """
        Renova o token usando o refresh_token
        
        :return: True se renovado com sucesso, False caso contrário
        """
        try:
            with self._token_lock:
                # Verifica se temos dados de token
                if not self._token_data or "refresh_token" not in self._token_data:
                    logger.error("Dados de token inexistentes ou incompletos")
                    return False
                
                refresh_token = self._token_data["refresh_token"]
            
            # Prepara a requisição
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            
            # Autenticação HTTP Basic
            auth = HTTPBasicAuth(self.client_id, self.client_secret)
            
            # Faz a requisição de forma síncrona
            response = requests.post(
                self.token_url,
                data=payload,
                headers=headers,
                auth=auth,
                timeout=10
            )
            
            if response.status_code == 200:
                new_token_data = response.json()
                
                # Adiciona timestamp de criação
                new_token_data["created_at"] = datetime.now().timestamp()
                
                with self._token_lock:
                    self._token_data = new_token_data
                
                # Salva o token
                self._save_token()
                
                logger.info(f"Token renovado com sucesso, expira em {new_token_data.get('expires_in', 'N/A')} segundos")
                return True
            else:
                logger.error(f"Erro ao renovar token: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro durante renovação do token: {str(e)}")
            return False
    
    def _is_token_expired_or_expiring_soon(self, threshold_seconds=600):
        """
        Verifica se o token está expirado ou prestes a expirar
        
        :param threshold_seconds: Tempo limite em segundos (padrão: 10 minutos)
        :return: True se expirado ou expirando em breve, False caso contrário
        """
        if not self._token_data:
            return True
            
        # Verifica se temos os campos necessários
        if "expires_in" not in self._token_data or "created_at" not in self._token_data:
            logger.warning("Token não tem campos expires_in ou created_at")
            return True
            
        # Calcula o tempo de vida do token
        created_timestamp = self._token_data["created_at"]
        expires_in_seconds = self._token_data["expires_in"]
        
        # Calcula quando o token expira
        expiry_timestamp = created_timestamp + expires_in_seconds
        current_timestamp = datetime.now().timestamp()
        
        # Tempo restante em segundos
        remaining_seconds = expiry_timestamp - current_timestamp
        
        # Verifica se está expirado ou expirando em breve
        if remaining_seconds <= threshold_seconds:
            logger.info(f"Token expira em {remaining_seconds:.1f} segundos (abaixo do limite de {threshold_seconds})")
            return True
        else:
            logger.debug(f"Token válido por mais {remaining_seconds:.1f} segundos")
            return False
    
    async def get_valid_token(self):
        """
        Obtém um token válido, renovando se necessário
        
        :return: Token de acesso válido ou None se não for possível obter
        """
        with self._token_lock:
            # Se não temos dados de token, não podemos fazer nada
            if not self._token_data or "access_token" not in self._token_data:
                logger.error("Não há token disponível")
                return None
            
            # Verifica se o token está expirado ou prestes a expirar
            needs_renewal = self._is_token_expired_or_expiring_soon()
            
        # Tenta renovar o token se necessário
        if needs_renewal:
            logger.info("Token expirado ou prestes a expirar, renovando...")
            success = await self.refresh_token()
            if not success:
                logger.warning("Falha ao renovar token automaticamente")
                
                # Se o token ainda é válido (apenas prestes a expirar), podemos usá-lo
                with self._token_lock:
                    if self._token_data and "access_token" in self._token_data:
                        if not self._is_token_expired_or_expiring_soon(threshold_seconds=0):  # Verifica se já expirou
                            logger.info("Usando token atual mesmo prestes a expirar")
                            return self._token_data.get("access_token")
                        else:
                            logger.error("Token expirado e falha na renovação")
                            return None
        
        # Retorna o token atual (renovado ou não)
        with self._token_lock:
            token = self._token_data.get("access_token") if self._token_data else None
            logger.info(f"Retornando token válido: {token[:15]}..." if token else "Nenhum token disponível")
            return token
    
    async def _renew_if_needed(self):
        """Verifica e renova o token se necessário"""
        with self._token_lock:
            needs_renewal = self._is_token_expired_or_expiring_soon(threshold_seconds=1800)  # 30 minutos
            
        if needs_renewal:
            logger.info("Executando renovação programada do token (verificação periódica)")
            await self.refresh_token()
    
    def start_renewal_job(self, interval_hours=1):
        """
        Inicia um job em background para renovação periódica do token
        
        :param interval_hours: Intervalo em horas para verificação (padrão: 1 hora)
        """
        if self._renewal_running:
            logger.info("Job de renovação já está em execução")
            return
        
        self._renewal_running = True
        
        async def renewal_job():
            """Job assíncrono para renovação periódica"""
            logger.info(f"Iniciando job de renovação com verificação a cada {interval_hours} horas")
            
            while self._renewal_running:
                try:
                    # Verifica e renova o token se necessário
                    await self._renew_if_needed()
                    
                    # Espera pelo intervalo (em segundos)
                    await asyncio.sleep(interval_hours * 60 * 60)
                    
                except asyncio.CancelledError:
                    logger.info("Job de renovação cancelado")
                    break
                except Exception as e:
                    logger.error(f"Erro no job de renovação: {str(e)}")
                    # Continua tentando após erro
                    await asyncio.sleep(60)  # Espera 1 minuto antes de tentar novamente
        
        # Inicia o job de renovação como uma tarefa assíncrona
        loop = asyncio.get_event_loop()
        self._renewal_task = loop.create_task(renewal_job())
        logger.info("Job de renovação iniciado")
    
    def stop_renewal_job(self):
        """Para o job de renovação periódica"""
        if not self._renewal_running:
            return
        
        self._renewal_running = False
        
        if self._renewal_task:
            self._renewal_task.cancel()
            logger.info("Job de renovação cancelado")
    
    async def ensure_token_file_exists(self, auth_code=None):
        """
        Garante que o arquivo de token existe, criando-o se necessário
        
        :param auth_code: Código de autorização para obter o token inicial
        :return: True se o arquivo existe ou foi criado, False caso contrário
        """
        # Se o arquivo já existe, apenas retorna
        if os.path.exists(self.token_file):
            return True
        
        # Se não temos código de autorização, não podemos criar o arquivo
        if not auth_code:
            logger.error("Arquivo de token não existe e nenhum código de autorização fornecido")
            return False
        
        # Tenta obter o token inicial
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": "https://530f-45-171-45-13.ngrok-free.app/callback"  # Use a URL de callback do seu app
        }
        
        # Autenticação HTTP Basic
        auth = HTTPBasicAuth(self.client_id, self.client_secret)
        
        try:
            response = requests.post(
                self.token_url,
                data=payload,
                headers=headers,
                auth=auth,
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Adiciona timestamp de criação
                token_data["created_at"] = datetime.now().timestamp()
                
                with self._token_lock:
                    self._token_data = token_data
                
                # Salva o token
                self._save_token()
                
                logger.info("Token inicial obtido e salvo com sucesso")
                return True
            else:
                logger.error(f"Erro ao obter token inicial: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao obter token inicial: {str(e)}")
            return False

# Função para renovar o token de forma forçada (útil para scripts)
async def force_token_renewal(client_id, client_secret):
    """
    Força a renovação do token do Bling
    
    :param client_id: Client ID do aplicativo Bling
    :param client_secret: Client Secret do aplicativo Bling
    :return: True se renovado com sucesso, False caso contrário
    """
    token_manager = BlingTokenManager(client_id, client_secret)
    logger.info("Forçando renovação do token Bling...")
    success = await token_manager.refresh_token()
    
    if success:
        logger.info("Token renovado com sucesso!")
        return True
    else:
        logger.error("Falha ao renovar token!")
        return False


# Exemplo de uso
if __name__ == "__main__":
    # Carrega variáveis de ambiente
    load_dotenv()
    
    # Credenciais do Bling
    CLIENT_ID = os.environ.get("BLING_CLIENT_ID", "")
    CLIENT_SECRET = os.environ.get("BLING_CLIENT_SECRET", "")
    
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.error("Variáveis BLING_CLIENT_ID e BLING_CLIENT_SECRET precisam estar definidas")
        exit(1)
    
    # Função de teste assíncrona
    async def test_token_manager():
        # Inicializa o gerenciador de token
        token_manager = BlingTokenManager(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        
        # Verifica se temos um token válido
        token = await token_manager.get_valid_token()
        
        if token:
            print(f"Token válido: {token[:15]}...")
            
            # Inicia job de renovação para teste
            token_manager.start_renewal_job(interval_hours=1)
            
            # Para demonstração, espera 10 segundos
            print("Job de renovação iniciado, esperando 10 segundos...")
            await asyncio.sleep(10)
            
            # Para o job
            token_manager.stop_renewal_job()
            print("Job de renovação parado")
        else:
            print("Não foi possível obter um token válido")
            
            # Se não temos token, podemos usar um código de autorização para obter
            auth_code = input("Digite um código de autorização (ou deixe em branco para sair): ")
            
            if auth_code:
                success = await token_manager.ensure_token_file_exists(auth_code)
                if success:
                    print("Token criado com sucesso!")
                else:
                    print("Falha ao criar token")
    
    # Executa teste
    asyncio.run(test_token_manager())