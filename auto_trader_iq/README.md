# AUTO TRADER IQ — Monitor OCR

Aplicativo local para selecionar uma região da tela, visualizar a captura e reconhecer por OCR etiquetas **COMPRA/COMPRAR**, **VENDER/VENDA**, **BUY** e **SELL**. O filtro visual limita os candidatos às barras recentes detectáveis; isso não comprova a identidade da vela nem a exatidão do sinal.

## Escopo oficial

- O aplicativo **somente captura e reconhece conteúdo visual**. Não envia cliques, não conecta à corretora, não cria nem acompanha ordens e não calcula resultados.
- A lista e o preview mostram candidatos OCR — não operações, entradas pendentes ou resultados financeiros.
- Não há dados fictícios carregados na inicialização nem histórico de operações.
- A configuração é salva localmente em `%LOCALAPPDATA%\AutoTraderIQ\config.json` no Windows (ou `~/.auto_trader_iq/config.json` em outros sistemas). Capturas de tela só são salvas quando solicitadas pelo usuário.
- Áreas ocultadas são mascaradas antes do OCR, do preview e do salvamento manual de captura.
- O OCR é local e exige Tesseract instalado separadamente. A confiança apresentada pelo Tesseract não é uma probabilidade calibrada de acerto.

O app não dispõe de integração com a corretora. Portanto, estados como **PENDENTE**, **CANCELADA**, **REJEITADA**, **EXPIRADA** ou **CONCLUÍDA** não são atribuídos a operações: o programa não recebe eventos de execução ou liquidação.

## Instalação no Windows

1. Instale Python 3.12 ou superior e o Tesseract OCR para Windows. Confirme que `python -m tkinter` funciona.
2. No PowerShell, dentro desta pasta:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

O Tesseract costuma estar em `C:\Program Files\Tesseract-OCR\tesseract.exe`; se estiver em outro local, informe o caminho na janela do aplicativo. O OCR permanece desligado até ser habilitado.

## Uso

Execute a partir desta pasta:

```powershell
python -m auto_trader_iq.app
```

1. Selecione o monitor e delimite toda a região relevante do gráfico.
2. Se controles da plataforma estiverem dentro da região, use **Ocultar área…** para mascará-los antes do processamento.
3. Habilite o reconhecimento OCR e inicie a visualização. O painel compacto pode ser movido para fora da região monitorada; **Configurações (pausar)** interrompe a captura e retorna à janela completa.
4. Confira visualmente as etiquetas e a imagem. OCR pode errar ou deixar de reconhecer sinais.

## Atualização

Feche o aplicativo e, na raiz do clone do projeto, execute:

```powershell
git pull origin arena/d4c07081-agency-agents
```

O código final deixa de ler e gravar o antigo `simulation_history.csv` e não usa mais a pasta `sequences`. Se esses arquivos/pastas existirem em `%LOCALAPPDATA%\AutoTraderIQ`, não são apagados automaticamente; são dados locais legados, fora do repositório. Confira ou arquive antes de removê-los manualmente.
