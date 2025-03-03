import json
import os
import time
import logging
import asyncio
import threading
import requests
import traceback
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from dotenv import load_dotenv
from whatsapp_client import create_whatsapp_client, MessageType

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bling_token_manager")

class BlingTokenManager:
    """
    Gerenciador de token para API Bling v3
    - Gerencia renovação automática de tokens
    - Verifica validade de tokens antes de requisições
    - Inicializa um job em background para renovação periódica
    - Mecanismo de recuperação quando o refresh token expira
    """
    
    def __init__(self, client_id, client_secret, token_file="bling_token.json", env_file=".env", 
                 auth_callback_url=None, webhook_url=None, whatsapp_config=None, admin_phone=None):
        """
        Inicializa o gerenciador de tokens
        
        :param client_id: Client ID do aplicativo Bling
        :param client_secret: Client Secret do aplicativo Bling
        :param token_file: Arquivo para armazenar os dados do token
        :param env_file: Arquivo .env para atualizar a variável BLING_API_KEY
        :param auth_callback_url: URL de callback para autorização OAuth2
        :param webhook_url: URL para notificação de webhook quando o token expirar
        :param whatsapp_config: Configuração para cliente WhatsApp
        :param admin_phone: Número de WhatsApp do administrador para receber alertas
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.env_file = env_file
        self.token_url = "https://www.bling.com.br/Api/v3/oauth/token"
        self.auth_callback_url = auth_callback_url
        self.webhook_url = webhook_url
        self.whatsapp_config = whatsapp_config
        self.admin_phone = admin_phone
        
        # Inicializa o cliente WhatsApp se configurado
        self.whatsapp_client = None
        if whatsapp_config and admin_phone:
            self.whatsapp_client = create_whatsapp_client(**whatsapp_config)
            logger.info(f"Cliente WhatsApp inicializado para notificações ao administrador: {admin_phone}")
        
        # Controle de estado de erro e recuperação
        self.error_state = False
        self.consecutive_failures = 0
        self.max_failures_before_alert = 3
        self.last_error_time = None
        self.backoff_minutes = 15  # Tempo inicial de espera entre tentativas após falha
        self.max_backoff_minutes = 120  # Tempo máximo de espera (2 horas)
        self.last_notification_time = None  # Para evitar spam de notificações
        self.min_notification_interval = 30  # Intervalo mínimo entre notificações (minutos)
        
        # Dados do token em memória
        self._token_data = None
        self._token_lock = threading.Lock()
        
        # Carrega token do arquivo, se existir
        self._load_token()
        
        # Flag para controlar o job de renovação
        self._renewal_running = False
        self._renewal_task = None
        
        logger.info("Gerenciador de token Bling inicializado")
    
     # Modifique o método _load_token no token_manager.py
    def _load_token(self):
        """Carrega os dados do token do arquivo com verificação de timestamp futuro"""
        try:
            if os.path.exists(self.token_file):
                # Armazena o timestamp de modificação
                self._last_token_mtime = os.path.getmtime(self.token_file)
                
                with open(self.token_file, "r") as file:
                    self._token_data = json.load(file)
                logger.info("Token carregado do arquivo")
                
                # NOVA VERIFICAÇÃO: Se created_at está no futuro, corrige para o timestamp atual
                if self._token_data and "created_at" in self._token_data:
                    future_threshold = time.time() + 3600  # 1 hora no futuro
                    if self._token_data["created_at"] > future_threshold:
                        logger.warning(f"⚠️ Timestamp futuro detectado no token: {self._token_data['created_at']}")
                        logger.warning(f"Data do token: {datetime.fromtimestamp(self._token_data['created_at']).strftime('%d/%m/%Y %H:%M:%S')}")
                        logger.warning(f"Data atual: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                        
                        # Corrige o timestamp para o atual
                        self._token_data["created_at"] = time.time() - 19000  # 5 horas atrás para forçar renovação
                        logger.warning(f"Timestamp corrigido para: {self._token_data['created_at']} (forçando renovação)")
                        
                        # Salva a correção
                        self._save_token()
                    
                # Verifica se o token tem campo created_at
                if self._token_data and "created_at" not in self._token_data:
                    logger.warning("Token carregado não tem campo created_at, adicionando timestamp atual")
                    self._token_data["created_at"] = time.time() - 19000  # 5 horas atrás para forçar renovação
                    self._save_token()
                    
                # Log informativo sobre validade
                if self._token_data and "access_token" in self._token_data and "expires_in" in self._token_data and "created_at" in self._token_data:
                    created_at = self._token_data["created_at"]
                    expires_in = self._token_data["expires_in"]
                    expiry_time = created_at + expires_in
                    current_time = time.time()
                    hours_remaining = (expiry_time - current_time) / 3600
                    
                    logger.info(f"Token carregado válido por mais {hours_remaining:.2f} horas")
            else:
                logger.warning(f"Arquivo de token {self.token_file} não encontrado")
        except Exception as e:
            logger.error(f"Erro ao carregar token: {str(e)}")
            self._token_data = {}

    def _save_token(self):
        """Salva os dados do token no arquivo"""
        try:
            with self._token_lock:
                with open(self.token_file, "w") as file:
                    json.dump(self._token_data, file, indent=2)
                
                # Atualiza o arquivo .env
                self._update_env_file()
                
                # Reset do estado de erro se o token foi salvo com sucesso
                self.error_state = False
                self.consecutive_failures = 0
                self.last_error_time = None
                self.backoff_minutes = 15  # Reset do tempo de backoff
                
            logger.info("Token salvo no arquivo")
        except Exception as e:
            logger.error(f"Erro ao salvar token: {str(e)}")
    
    def _update_env_file(self):
        """Atualiza a variável BLING_API_KEY no arquivo .env"""
        try:
            if not os.path.exists(self.env_file) or not self._token_data or "access_token" not in self._token_data:
                return
                
            with open(self.env_file, "r") as f:
                lines = f.readlines()
                
            access_token = self._token_data["access_token"]
            updated = False
            updated_lines = []
            
            # Marca para remover o comentário de data antigo
            remove_next = False
            
            for line in lines:
                # Se esta linha é para remover (comentário antigo)
                if remove_next:
                    remove_next = False
                    continue
                    
                # Se encontrou a linha de comentário data antiga
                if "# Token Bling gerado em" in line:
                    remove_next = False  # Não precisamos mais remover a próxima linha
                    continue  # Pula esta linha
                    
                # Se é a linha do token
                if line.strip().startswith("BLING_API_KEY="):
                    # Adiciona comentário com data atual
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated_lines.append(f"# Token Bling gerado em {current_time}\n")
                    updated_lines.append(f"BLING_API_KEY={access_token}\n")
                    updated = True
                else:
                    updated_lines.append(line)
            
            if not updated:
                # Se não encontrou a linha do token, adiciona ao final
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                updated_lines.append(f"\n# Token Bling gerado em {current_time}\n")
                updated_lines.append(f"BLING_API_KEY={access_token}\n")
            
            # Escreve o arquivo atualizado
            with open(self.env_file, "w") as env_file:
                env_file.writelines(updated_lines)
            
            # Também atualiza a variável de ambiente atual
            os.environ["BLING_API_KEY"] = access_token
            
            logger.info("Arquivo .env atualizado com o novo token")
        except Exception as e:
            logger.error(f"Erro ao atualizar arquivo .env: {str(e)}")
    
    async def _should_attempt_recovery(self):
        """
        Verifica se deve tentar recuperação baseado no estado de erro e tempo de backoff
        
        :return: True se deve tentar recuperação, False caso contrário
        """
        if not self.error_state:
            return True
            
        if not self.last_error_time:
            self.last_error_time = datetime.now()
            return True
            
        # Calcula tempo decorrido desde o último erro
        elapsed = datetime.now() - self.last_error_time
        
        # Tempo de backoff exponencial (2^n) limitado pelo máximo
        current_backoff = min(self.backoff_minutes * (2 ** (self.consecutive_failures - 1)), 
                              self.max_backoff_minutes)
        
        logger.info(f"Tempo desde último erro: {elapsed.total_seconds() / 60:.1f} minutos, " +
                   f"Backoff atual: {current_backoff} minutos")
        
        # Se o tempo decorrido for maior que o backoff, tenta novamente
        if elapsed.total_seconds() > (current_backoff * 60):
            return True
            
        return False
    
    async def refresh_token(self):
        """
        Renova o token usando o refresh_token
        
        :return: True se renovado com sucesso, False caso contrário
        """
        # Verifica se deve tentar recuperação baseado no estado de backoff
        if not await self._should_attempt_recovery():
            logger.warning(f"Em período de backoff, aguardando antes da próxima tentativa")
            return False
        
        try:
            with self._token_lock:
                # Verifica se temos dados de token
                if not self._token_data or "refresh_token" not in self._token_data:
                    logger.error("Dados de token inexistentes ou incompletos")
                    
                    # Primeira falha, tenta recuperação imediata
                    if self.consecutive_failures == 0:
                        self.consecutive_failures += 1
                        self.last_error_time = datetime.now()
                        
                        # NOVO: Tenta client_credentials primeiro
                        client_cred_success = await self._try_client_credentials()
                        if client_cred_success:
                            return True
                            
                        # Se falhar, tenta o método tradicional
                        await self._attempt_token_recovery()
                    
                    return False
                
                refresh_token = self._token_data["refresh_token"]
            
            # NOVO: Verifica se o token já venceu há muito tempo (mais de 12 horas)
            # Se sim, é mais eficiente tentar diretamente com client_credentials
            with self._token_lock:
                if self._token_data and "created_at" in self._token_data and "expires_in" in self._token_data:
                    created_at = self._token_data["created_at"]
                    expires_in = self._token_data["expires_in"]
                    expiry_time = created_at + expires_in
                    current_time = time.time()
                    
                    # Se expirado há mais de 12 horas, é improvável que o refresh token funcione
                    hours_expired = (current_time - expiry_time) / 3600
                    if current_time > (expiry_time + 43200):  # 43200 segundos = 12 horas
                        logger.warning(f"Token expirado há {hours_expired:.1f} horas, pulando refresh_token e tentando client_credentials")
                        client_cred_success = await self._try_client_credentials()
                        if client_cred_success:
                            return True
                        # Se client_credentials falhar, continua com refresh_token como fallback
            
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
            
            # NOVO: Implementa retry para problemas de conexão
            for attempt in range(3):  # 3 tentativas
                try:
                    # Faz a requisição com timeout maior
                    response = requests.post(
                        self.token_url,
                        data=payload,
                        headers=headers,
                        auth=auth,
                        timeout=30  # Timeout aumentado
                    )
                    
                    # Se conseguiu resposta, sai do loop
                    break
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(f"Erro de conexão na tentativa {attempt+1}/3: {str(e)}")
                    if attempt < 2:  # Se não for a última tentativa
                        await asyncio.sleep(2 * (attempt + 1))  # Backoff progressivo: 2s, 4s
                    else:
                        logger.error("Todas as tentativas de conexão falharam")
                        raise  # Re-lança a exceção na última tentativa
            
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
                # Incrementa o contador de falhas
                self.consecutive_failures += 1
                self.last_error_time = datetime.now()
                
                # Detecta erro específico de "invalid_grant"
                error_message = "Erro desconhecido"
                is_invalid_grant = False
                
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        if isinstance(error_data["error"], dict):
                            error_type = error_data["error"].get("type")
                            error_message = error_data["error"].get("message", "Sem detalhes")
                            is_invalid_grant = error_type == "invalid_grant"
                        else:
                            error_type = error_data["error"]
                            error_message = error_data.get("message", "Sem detalhes")
                            is_invalid_grant = error_type == "invalid_grant"
                except Exception as e:
                    logger.error(f"Erro ao analisar resposta JSON: {str(e)}")
                    error_message = response.text
                
                logger.error(f"Erro ao renovar token: {response.status_code} - {error_message}")
                
                # Se for um erro "invalid_grant", tenta recuperação automatizada
                if is_invalid_grant:
                    logger.warning("Refresh token inválido ou expirado, tentando recuperação automática")
                    
                    # Entra em estado de erro
                    self.error_state = True
                    
                    # Notifica sobre o erro se tiver atingido o limite de falhas consecutivas
                    if self.consecutive_failures >= self.max_failures_before_alert:
                        await self._notify_token_failure(error_message)
                    
                    # NOVO: Tenta client_credentials primeiro (mais eficaz)
                    client_cred_success = await self._try_client_credentials()
                    if client_cred_success:
                        return True
                    
                    # Se falhar, tenta o método tradicional
                    await self._attempt_token_recovery()
                
                return False
                
        except Exception as e:
            logger.error(f"Erro durante renovação do token: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Incrementa contador de falhas
            self.consecutive_failures += 1
            self.last_error_time = datetime.now()
            
            # Se atingiu limite de falhas, notifica
            if self.consecutive_failures >= self.max_failures_before_alert:
                await self._notify_token_failure(str(e))
            
            return False
    
    async def _attempt_token_recovery(self):
        """
        Tenta recuperar o token automaticamente quando o refresh token expira
        """
        logger.info(f"Tentativa {self.consecutive_failures} de recuperação automática do token")
        
        # 1. NOVO: Tenta primeiro com client_credentials (método mais robusto)
        try:
            logger.info("Tentando primeiro recuperação com client_credentials...")
            success = await self._try_client_credentials()
            if success:
                logger.info("✅ Recuperação com client_credentials bem-sucedida!")
                return
            else:
                logger.warning("❌ Falha na recuperação com client_credentials, tentando alternativas...")
        except Exception as e:
            logger.error(f"Erro na tentativa de client_credentials: {str(e)}")
        
        # 2. Tenta usar o webhook para restauração automatizada (método original)
        if self.webhook_url:
            try:
                logger.info(f"Enviando requisição para webhook de recuperação: {self.webhook_url}")
                
                # Prepara dados para o webhook
                webhook_data = {
                    "event": "token_expired",
                    "client_id": self.client_id,
                    "timestamp": datetime.now().isoformat(),
                    "attempts": self.consecutive_failures
                }
                
                # Envia requisição para o webhook
                webhook_response = requests.post(
                    self.webhook_url,
                    json=webhook_data,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                
                if webhook_response.status_code in (200, 201, 202, 204):
                    logger.info(f"Webhook de recuperação enviado com sucesso: {webhook_response.status_code}")
                    return  # Não faz nada mais, aguarda o webhook responder
                else:
                    logger.warning(f"Falha ao chamar webhook: {webhook_response.status_code} - {webhook_response.text}")
            except Exception as e:
                logger.error(f"Erro ao enviar webhook de recuperação: {str(e)}")
        
        # 3. Se muitas falhas e não tem webhook, tenta backup mais drástico: 
        # deletar o arquivo de token para forçar nova autenticação
        if self.consecutive_failures > 10 and os.path.exists(self.token_file):
            try:
                # Antes de deletar, faz backup do arquivo
                backup_file = f"{self.token_file}.bak.{int(time.time())}"
                
                with open(self.token_file, "r") as src:
                    with open(backup_file, "w") as dst:
                        dst.write(src.read())
                
                # Deleta o arquivo de token
                os.remove(self.token_file)
                logger.warning(f"Arquivo de token deletado após {self.consecutive_failures} falhas. " +
                            f"Backup criado em: {backup_file}")
                
                # Limpa dados em memória
                with self._token_lock:
                    self._token_data = None
                
                # Notifica sobre essa ação
                await self._notify_token_failure(
                    f"Token foi deletado após {self.consecutive_failures} falhas. " +
                    "Uma nova autorização completa será necessária no próximo uso."
                )
            except Exception as e:
                logger.error(f"Erro ao deletar arquivo de token: {str(e)}")
    
    async def _notify_token_failure(self, error_details):
        """
        Notifica sobre falha na recuperação do token via WhatsApp
        
        :param error_details: Detalhes do erro
        """
        # Verifica se já enviou notificação recentemente (evita spam)
        if self.last_notification_time:
            elapsed = datetime.now() - self.last_notification_time
            if elapsed.total_seconds() < (self.min_notification_interval * 60):
                logger.info(f"Notificação ignorada (enviada há {elapsed.total_seconds() / 60:.1f} minutos)")
                return
        
        # Prepara a mensagem
        message = f"""🚨 *ALERTA: TOKEN BLING EXPIRADO* 🚨

⏰ *{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}*

❌ *Problema*: O token do Bling expirou e não foi possível renová-lo automaticamente.

🔄 *Tentativas*: {self.consecutive_failures}
⚠️ *Erro*: {error_details}

📱 *Ações necessárias*:
1. Acesse o painel do Bling
2. Revogue a autorização atual 
3. Autorize novamente o aplicativo
4. Obtenha um novo código e use-o para gerar um token

🔗 *Link para autorização*:
{self.get_auth_url()}

⚠️ Este problema impede a sincronização com o Bling!"""
        
        # Envia a mensagem via WhatsApp
        if self.whatsapp_client and self.admin_phone:
            try:
                logger.info(f"Enviando notificação para o WhatsApp: {self.admin_phone}")
                success = await self.whatsapp_client.send_message(
                    text=message,
                    number=self.admin_phone,
                    message_type=MessageType.TEXT,
                    simulate_typing=False
                )
                
                if success:
                    logger.info("Notificação WhatsApp enviada com sucesso")
                    self.last_notification_time = datetime.now()
                else:
                    logger.error("Falha ao enviar notificação via WhatsApp")
            except Exception as e:
                logger.error(f"Erro ao enviar notificação via WhatsApp: {str(e)}")
        else:
            logger.warning("Cliente WhatsApp não configurado, não é possível enviar notificação")
        
        # Log detalhado
        logger.critical(f"ALERTA CRÍTICO: Falha de token irrecuperável:\n{message}")
    
    def get_auth_url(self):
        """
        Gera URL para autorização manual
        
        :return: URL de autorização
        """
        base_url = "https://www.bling.com.br/Api/v3/oauth/authorize"
        redirect_uri = self.auth_callback_url or "https://estoqueml.luarshop.com.br/callback"
        
        auth_url = (
            f"{base_url}?response_type=code&client_id={self.client_id}"
            f"&redirect_uri={redirect_uri}&scope=abilitado&state=autorizacao"
        )
        
        return auth_url
    
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
        
    async def _try_client_credentials(self):
        """
        Tenta recuperar um token usando client_credentials quando o refresh_token falha
        
        :return: True se bem-sucedido, False caso contrário
        """
        try:
            logger.info("🔑 Tentando recuperação com client_credentials grant...")
            
            # Verifica se temos credenciais necessárias
            if not self.client_id or not self.client_secret:
                logger.error("❌ Client ID ou Secret não disponíveis para client_credentials")
                return False
            
            # Prepara a requisição
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            auth = HTTPBasicAuth(self.client_id, self.client_secret)
            
            # O Bling aceita client_credentials com os escopos apropriados
            payload = {
                "grant_type": "client_credentials",
                "scope": "Api.Estoque Api.Produtos"  # Escopos essenciais para consulta de produtos
            }
            
            # Faz a requisição
            response = requests.post(
                self.token_url,
                headers=headers,
                auth=auth,
                data=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                new_token_data = response.json()
                
                # Adiciona timestamp de criação
                new_token_data["created_at"] = datetime.now().timestamp()
                
                with self._token_lock:
                    self._token_data = new_token_data
                
                # Salva o token
                self._save_token()
                
                logger.info(f"✅ Token obtido com sucesso via client_credentials. Válido por {new_token_data.get('expires_in', 0) / 3600:.1f} horas")
                return True
            else:
                logger.error(f"❌ Falha na recuperação com client_credentials: {response.status_code}")
                try:
                    error_data = response.json()
                    error_type = error_data.get("error", "desconhecido")
                    error_desc = error_data.get("error_description", "Sem detalhes")
                    logger.error(f"  Detalhes: {error_type} - {error_desc}")
                except:
                    logger.error(f"  Resposta: {response.text}")
                
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro durante recuperação com client_credentials: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False    
    
    async def get_valid_token(self):
        """
        Obtém um token válido, renovando se necessário
        
        :return: Token de acesso válido ou None se não for possível obter
        """
        try:
            # Verificar se o arquivo de token foi modificado desde o último carregamento
            if os.path.exists(self.token_file):
                current_mtime = os.path.getmtime(self.token_file)
                if not hasattr(self, '_last_token_mtime') or current_mtime > self._last_token_mtime:
                    # Arquivo foi modificado externamente (por exemplo, pelo script renew_token.py)
                    logger.info("Arquivo de token foi modificado externamente, recarregando...")
                    self._load_token()
            
            # Se está em estado de erro, verifica se deve tentar novamente
            if self.error_state and not await self._should_attempt_recovery():
                logger.warning("Em estado de erro e período de backoff, não tentando obter token")
                return None
            
            with self._token_lock:
                # Se não temos dados de token, não podemos fazer nada
                if not self._token_data or "access_token" not in self._token_data:
                    logger.error("Não há token disponível")
                    
                    # NOVO: Tenta gerar um token com client_credentials se não tiver token
                    logger.info("Tentando criar um novo token com client_credentials")
                    success = await self._try_client_credentials()
                    if success:
                        logger.info("Novo token obtido com client_credentials")
                        return self._token_data.get("access_token")
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
                                # NOVO: Tenta uma última vez com client_credentials
                                success = await self._try_client_credentials()
                                if success:
                                    return self._token_data.get("access_token")
                                return None
            
            # Retorna o token atual (renovado ou não)
            with self._token_lock:
                token = self._token_data.get("access_token") if self._token_data else None
                if token:
                    logger.debug(f"Retornando token válido: {token[:15]}...")
                else:
                    logger.error("Nenhum token disponível")
                return token
                
        except Exception as e:
            logger.error(f"Erro ao obter token válido: {str(e)}")
            logger.error(traceback.format_exc())
            # Em caso de erro, tenta recuperação
            self.consecutive_failures += 1
            await self._attempt_token_recovery()
            return None
    
    async def _renew_if_needed(self):
        """Verifica e renova o token se necessário"""
        # Tenta limpar o estado de erro se estiver há muito tempo sem tentar
        if self.error_state and await self._should_attempt_recovery():
            logger.info("Saindo do estado de erro para verificar token")
            self.error_state = False
        
        with self._token_lock:
            needs_renewal = self._is_token_expired_or_expiring_soon(threshold_seconds=1800)  # 30 minutos
            
        if needs_renewal:
            logger.info("Executando renovação programada do token (verificação periódica)")
            await self.refresh_token()
    
    def start_renewal_job(self, interval_hours=1):
        """Versão melhorada do início do job de renovação"""
        if self._renewal_running:
            logger.info("Job de renovação já está em execução")
            return
        
        # Cancela qualquer tarefa anterior
        if hasattr(self, '_renewal_task') and self._renewal_task:
            self._renewal_task.cancel()
        
        self._renewal_running = True
        
        async def renewal_job():
            """Job assíncrono para renovação periódica com verificação de saúde"""
            logger.info(f"Iniciando job de renovação com verificação a cada {interval_hours} horas")
            
            # Verificação imediata na inicialização
            await self._renew_if_needed()
            
            while self._renewal_running:
                try:
                    # Intervalo mais curto para verificação mais frequente
                    check_interval = 15 * 60  # 15 minutos
                    
                    # Dividir o tempo de espera em intervalos menores
                    # para que possamos verificar self._renewal_running com mais frequência
                    chunks = int((interval_hours * 3600) / check_interval)
                    
                    for _ in range(chunks):
                        if not self._renewal_running:
                            break
                        await asyncio.sleep(check_interval)
                        # Verificação periódica durante o intervalo
                        await self._renew_if_needed()
                    
                except asyncio.CancelledError:
                    logger.info("Job de renovação cancelado")
                    break
                except Exception as e:
                    logger.error(f"Erro no job de renovação: {str(e)}")
                    # Continua tentando após erro (com tempo reduzido)
                    await asyncio.sleep(60)
        
        # Mantém referência à tarefa e adiciona nome para depuração
        loop = asyncio.get_event_loop()
        self._renewal_task = loop.create_task(renewal_job())
        self._renewal_task.set_name("token_renewal_job")
        logger.info("Job de renovação iniciado com verificações a cada 15 minutos")
        
        # Retorna a tarefa para que o chamador possa monitorá-la se desejar
        return self._renewal_task
    
    def stop_renewal_job(self):
        """Para o job de renovação periódica"""
        if not self._renewal_running:
            return
        
        self._renewal_running = False
        
        if self._renewal_task:
            self._renewal_task.cancel()
            logger.info("Job de renovação cancelado")
    
    async def create_token_from_auth_code(self, auth_code, redirect_uri=None):
        """
        Cria um novo token usando o código de autorização
        
        :param auth_code: Código de autorização do fluxo OAuth
        :param redirect_uri: URI de redirecionamento (deve ser o mesmo usado na autorização)
        :return: True se token criado com sucesso, False caso contrário
        """
        try:
            # URI de redirecionamento padrão se não fornecido
            if not redirect_uri and self.auth_callback_url:
                redirect_uri = self.auth_callback_url
            elif not redirect_uri:
                redirect_uri = "https://estoqueml.luarshop.com.br/callback"  # Valor padrão (ajustar conforme necessário)
            
            logger.info(f"Criando novo token a partir do código de autorização")
            
            # Prepara a requisição
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            payload = {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri
            }
            
            # Autenticação HTTP Basic
            auth = HTTPBasicAuth(self.client_id, self.client_secret)
            
            # Faz a requisição
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
                
                # Reset dos estados de erro
                self.error_state = False
                self.consecutive_failures = 0
                self.last_error_time = None
                
                # Notifica sobre o sucesso via WhatsApp
                if self.whatsapp_client and self.admin_phone:
                    success_message = f"""✅ *Token Bling Renovado com Sucesso!*

⏰ *{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}*

O token do Bling foi renovado com sucesso e a integração voltou a funcionar normalmente.

📊 *Detalhes:*
- Validade: {token_data.get('expires_in', 0) // 3600} horas
- Renovação automática: ✅ Ativada

Nenhuma ação adicional é necessária."""

                    await self.whatsapp_client.send_message(
                        text=success_message,
                        number=self.admin_phone,
                        message_type=MessageType.TEXT,
                        simulate_typing=False
                    )
                
                logger.info("Token criado com sucesso!")
                return True
            else:
                logger.error(f"Erro ao criar token: {response.status_code} - {response.text}")
                return False
        
        except Exception as e:
            logger.error(f"Erro ao criar token a partir do código: {str(e)}")
            return False