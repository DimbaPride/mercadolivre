# Bling Stock Monitor

Sistema de monitoramento de estoque do Bling com integração WhatsApp (Evolution API).

## Funcionalidades

- Monitoramento automático de estoque no Bling
- Monitoramento de múltiplos depósitos (Full e Normal)
- Envio de alertas via WhatsApp para grupo
- Configuração via variáveis de ambiente
- Logging detalhado das operações

## Estrutura do Projeto

```
projeto/
├── .env.example         # Template para configurações
├── .gitignore          # Arquivos ignorados pelo git
├── README.md           # Esta documentação
├── requirements.txt    # Dependências do projeto
├── main.py            # Arquivo principal
├── settings.py        # Gerenciamento de configurações
├── bling_stock_monitor.py  # Monitor de estoque
└── whatsapp_client.py # Cliente WhatsApp
```

## Configuração

1. Clone o repositório
```bash
git clone https://github.com/seu-usuario/bling-stock-monitor.git
cd bling-stock-monitor
```

2. Crie um ambiente virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. Instale as dependências
```bash
pip install -r requirements.txt
```

4. Configure o ambiente
```bash
cp .env.example .env
# Edite o arquivo .env com suas configurações
```

## Execução

```bash
python main.py
```

## Desenvolvimento

Para contribuir com o projeto:

1. Crie uma branch para sua feature
```bash
git checkout -b feature/nova-funcionalidade
```

2. Faça commit das alterações
```bash
git add .
git commit -m "Adiciona nova funcionalidade"
```

3. Envie para o repositório
```bash
git push origin feature/nova-funcionalidade
```