# AUTO TRADER IQ — OCR e simulação manual assistida

Aplicativo local para capturar uma região da tela, reconhecer etiquetas COMPRA/COMPRAR, VENDER/VENDA, BUY e SELL por OCR e apresentar candidatos para revisão. Durante a captura, pode usar o painel compacto com prévia ao vivo e marcações OCR. Áreas ocultadas são mascaradas antes do OCR, da prévia e do salvamento de imagens.

## Escopo

- A **simulação assistida é manual**: o usuário arma um candidato e confirma visualmente a abertura da vela seguinte. O resultado é registrado como **SIMULADO**, nunca como ordem real.
- O aplicativo **não envia cliques**, não se conecta à corretora, não verifica aceitação da ordem e não calcula WIN/LOSS.
- O OCR pode errar e não comprova a identidade da vela. A confiança do Tesseract não é uma probabilidade calibrada.
- O histórico local registra metadados de sinais e entradas simuladas. Não armazena imagens nem transmite informações pela rede.
- A gravação opcional de sequências captura imagens localmente por até 75 segundos para revisão visual; não executa operações.

## Instalação no Windows

1. Instale Python 3.12 ou superior e confirme que `python -m tkinter` funciona.
2. Instale o Tesseract OCR para Windows separadamente. `pytesseract` é apenas o adaptador Python. O caminho padrão frequente é `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. No PowerShell, dentro desta pasta:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

Crie a venv uma vez e reutilize-a. Se o Tesseract estiver em outro local, informe o executável na janela. O OCR permanece desligado até ser habilitado.

## Uso

Inicie o aplicativo nesta pasta:

```powershell
python -m auto_trader_iq.app
```

1. Selecione o monitor e a região completa do gráfico. Evite incluir a janela do AUTO TRADER, menus e controles da plataforma.
2. Se um botão ou painel precisar ficar dentro do recorte, use **Ocultar área dos botões do OCR/capturas…** para mascará-lo.
3. Habilite o reconhecimento OCR e inicie a visualização. A lista apresenta etiquetas recentes associadas às barras detectadas; confira cada candidato no gráfico e na prévia.
4. Selecione um candidato e escolha **Armar candidato selecionado**. Para M1, a confirmação fica disponível quando o relógio HORA ATUAL avança exatamente um minuto desde o armamento e está nos primeiros 30 segundos. Confira visualmente que N+1 nasceu antes de confirmar. Leituras ausentes, atrasadas ou com minutos pulados bloqueiam a confirmação.
5. Use **Cancelar** para encerrar um sinal pendente. O pendente não é uma operação enviada à corretora.

## Histórico e dados locais

O histórico fica em `%LOCALAPPDATA%\AutoTraderIQ\simulation_history.csv` no Windows (ou `~/.auto_trader_iq/simulation_history.csv` em outros sistemas). A interface e a exportação incluem somente entradas **simuladas manualmente**; registros antigos de cliques automáticos não são mostrados nem exportados. Eles não são apagados automaticamente para preservar o CSV existente. **Salvar todas as entradas…** exporta as entradas simuladas; **Limpar log…** remove permanentemente o histórico local após confirmação.

As configurações são salvas em `%LOCALAPPDATA%\AutoTraderIQ\config.json`. Capturas manuais ficam em `%LOCALAPPDATA%\AutoTraderIQ\screenshots`. As sequências opcionais ficam em `%LOCALAPPDATA%\AutoTraderIQ\sequences`. Arquivos locais existentes não são apagados automaticamente.

## Gravação opcional de sequência

Com a captura M1 e o OCR ativos, **Gravar sequência de teste (75 s)** salva aproximadamente uma imagem por segundo por até 75 segundos; pode ser interrompida manualmente. A captura e o manifesto permanecem neste computador. Confira o recorte para não gravar dados pessoais. A gravação serve apenas para revisão, não confirma N+1 e não executa operações.

Para atualizar o código, feche o aplicativo e, na raiz do clone Git, execute:

```powershell
git pull origin arena/d4c07081-agency-agents
```
