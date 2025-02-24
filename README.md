# Monitor de Estoque Bling + WhatsApp

Sistema de monitoramento automático de estoque do Bling com integração WhatsApp via Evolution API. O sistema monitora níveis de estoque em dois depósitos (Full e Principal) e envia alertas automáticos para um grupo do WhatsApp quando produtos atingem estoque zero ou negativo.

## Funcionalidades

- 🔄 **Monitoramento via Webhook**: Recebe atualizações em tempo real do Bling
- 📦 **Múltiplos Depósitos**: Monitora Depósito Full e Principal separadamente
- 👨‍👩‍👧‍👦 **Grupo WhatsApp**: Envia alertas automáticos para grupo configurado
- 🎯 **Detecção Inteligente**: Identifica produtos pai e suas variações
- ⏱️ **Anti-Spam**: Evita duplicidade de alertas no mesmo dia
- 📝 **Logs Detalhados**: Registro completo de operações para diagnóstico

## Endpoints

- `/` - Verifica status do servidor
- `/full` - Recebe webhooks do Depósito Full
- `/principal` - Recebe webhooks do Depósito Principal

## Configuração

1. Clone o repositório:
```bash
git clone https://github.com/DimbaPride/mercadolivre.git
cd mercadolivre
```

2. Crie o arquivo `.env` com as seguintes variáveis:
```env
BLING_API_KEY=sua_chave_api_bling
WHATSAPP_API_KEY=sua_chave_api_evolution
WHATSAPP_API_URL=url_evolution_api
WHATSAPP_INSTANCE=nome_instancia
CHECK_INTERVAL=30
```

3. Instale as dependências:
```bash
pip install -r requirements.txt
```

4. Execute o servidor:
```bash
python main.py
```

## Formato das Mensagens

O sistema envia alertas formatados com a seguinte estrutura:
```
🚨 ALERTA DE ESTOQUE - DD/MM/YYYY HH:MM

Produtos com estoque zerado ou negativo:

🏪 Depósito Full
📦 Nome do Produto Pai
(SKU PAI: XXXXX)

   Variações com estoque zerado: ⚠️
   • Variação 1 (SKU: XXXXX)
   • Variação 2 (SKU: XXXXX)

🏪 Depósito Principal
📦 Produto Individual
   SKU: XXXXX
   Estoque: 0

ℹ️ Este é um alerta automático do sistema de monitoramento.
Verifique e atualize os estoques conforme necessário.
```

## Requisitos

- Python 3.9+
- FastAPI
- Evolution API (WhatsApp)
- Acesso à API do Bling

## Recursos do Sistema

- Suporte a webhooks do Bling
- Processamento assíncrono com FastAPI
- Sistema de logging detalhado
- Validação de configurações
- Tratamento de diferentes tipos de payload (JSON e form-data)
- Identificação automática de produtos pai/variações