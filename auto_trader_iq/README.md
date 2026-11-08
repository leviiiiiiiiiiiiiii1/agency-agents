# AUTO TRADER IQ — OCR e cliques automáticos

Aplicativo local que captura uma região da tela, reconhece etiquetas COMPRA/COMPRAR, VENDER/VENDA, BUY e SELL por OCR e mostra candidatos para revisão. Também mantém um fluxo separado de simulação manual e oferece **cliques automáticos opcionais**, habilitados pelo usuário em cada sessão.

## Automação de cliques

Os cliques automáticos ficam desligados até serem ativados explicitamente. No Windows, o usuário calibra os alvos COMPRAR e VENDER e escolhe o segundo fixo entre `:00` e `:30` (padrão `:05`). Um sinal reconhecido antes desse segundo é armado e aguarda o horário configurado; um sinal reconhecido depois é descartado naquela vela. Não há prazo individual entre armar o sinal e o clique. A ativação contínua pode ser configurada entre **15 e 28.800 segundos (8 horas; 75 segundos por padrão)**, com no máximo uma tentativa por minuto M1. Uma nova leitura OCR que não mostre mais a etiqueta armada cancela a tentativa.

O relógio do Windows convertido para UTC−3 define a janela M1 da automação. Na ativação, o app ancora o relógio no instante UTC do Windows e o avança monotonicamente durante a sessão. Ele não é sincronizado com a corretora e pode divergir em segundos; a leitura OCR de HORA ATUAL não determina o horário do clique. A captura/prévia atualiza até 4 vezes por segundo e OCR/análise rodam fora da thread da interface; quadros cuja análise leve mais de 1,5 s são descartados para evitar sinais defasados. Isso não cria um prazo individual entre armar o sinal e o segundo de clique configurado. Se o rótulo desaparecer numa nova leitura, a tentativa pendente é cancelada. A automação não espera N+1 e pode clicar ainda durante a vela N. As travas contra repetição valem durante a sessão e são reiniciadas ao fechar o app; um rótulo antigo que continue visível pode ser reconsiderado após a virada do minuto.

O app não verifica a conta selecionada, o valor, a expiração, a identidade visual da vela ou se a plataforma aceitou o clique. **Um clique pode enviar uma ordem real.** Antes de ativar, confira a conta e todos os parâmetros diretamente na plataforma. Não use a automação se não puder confirmar a configuração correta. Na calibração, a janela e a posição dos botões são registradas e revalidadas antes do clique; se outra janela cobrir os alvos, a automação é bloqueada até que a plataforma seja trazida à frente e os botões sejam recalibrados.

O movimento opcional do cursor sem clique é uma configuração separada: ocorre apenas após inatividade, entre pontos neutros calibrados e durante uma ativação explícita. Pode alterar efeitos de foco/hover da plataforma.

## Simulação manual e OCR

A simulação manual continua disponível: o usuário arma um candidato e confirma visualmente que a vela N+1 nasceu. Em M1, a confirmação usa a leitura HORA ATUAL da plataforma, exige avanço de exatamente um minuto desde o armamento e fica limitada aos primeiros 30 segundos. Leituras ausentes, atrasadas ou com minutos pulados bloqueiam a confirmação. A entrada resultante é registrada como **SIMULADA** e não é enviada à corretora.

A confiança do Tesseract não é uma probabilidade calibrada. Quando a leitura normal não encontra etiquetas, o app faz uma segunda leitura OCR isolando pixels verdes/vermelhos; candidatos desse recurso só passam quando a cor confirma COMPRA/BUY (verde) ou VENDER/SELL (vermelho). Na leitura normal, conflito de cor também descarta o candidato, enquanto texto sem cor confiável continua dependendo do OCR. O filtro visual de velas reconhece, entre outras, as paletas verde/vermelha e branca/roxa e tenta associar etiquetas às barras recentes. Essas heurísticas não comprovam a identidade da vela; confira os candidatos e a prévia antes de qualquer ação.

O painel **Contexto do gráfico** é somente informativo e analisa até as 12 velas visíveis mais recentes por cores e geometria. Estima lateralização por sobreposição e pouco deslocamento, pavios/retrações pela proporção dos pavios ao corpo e fluxo comprador/vendedor pela progressão dos fechamentos. “Fluxo” aqui significa movimento de preço visível, não dados de book/negócios; a classificação é heurística, pode oscilar com zoom/tema e não habilita nem altera cliques automáticos.

## Instalação e execução no Windows

1. Instale Python 3.12 ou superior e confirme que `python -m tkinter` funciona.
2. Instale o Tesseract OCR para Windows separadamente. O caminho padrão frequente é `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. No PowerShell, dentro desta pasta:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m auto_trader_iq.app
```

O OCR fica desligado até ser habilitado. Se o Tesseract estiver em outro local, informe o executável na janela.

## Uso

1. Selecione o monitor e toda a região relevante do gráfico. Use **Ocultar área dos botões do OCR/capturas…** para mascarar partes que não devem ser processadas.
2. Habilite o reconhecimento OCR e inicie a visualização. O painel compacto mostra prévia ao vivo e etiquetas reconhecidas; mantenha-o fora da região capturada.
3. Para a automação, calibre os botões COMPRAR e VENDER, confira as configurações da plataforma e habilite **Ativar cliques automáticos…**. A ativação é interrompida manualmente pelo botão **Parar cliques automáticos** ou ao atingir o limite configurado.
4. Para a simulação manual, selecione um candidato, use **Armar candidato selecionado** e confirme N+1 somente depois de observá-la visualmente.

As áreas ocultadas são mascaradas antes do OCR, da prévia, das capturas salvas e das gravações de sequência. A opção do Windows para manter a tela/computador ativos permanece desligada por padrão.

## Histórico e arquivos locais

O histórico em `%LOCALAPPDATA%\AutoTraderIQ\simulation_history.csv` (Windows) registra metadados de sinais, entradas simuladas e tentativas de clique; não contém imagens e não é transmitido. A interface identifica separadamente entradas **SIMULADAS** e tentativas **AUTOMÁTICAS**. Tentativa de clique não significa ordem aceita nem resultado financeiro. **Salvar todas as entradas…** exporta os registros; **Limpar log…** apaga o CSV após confirmação.

Arquivos de dados: `%LOCALAPPDATA%\AutoTraderIQ` no Windows ou `~/.auto_trader_iq` em outros sistemas. A configuração fica em `config.json`, o histórico em `simulation_history.csv`, as capturas manuais em `screenshots` e as gravações opcionais em `sequences`. Arquivos locais não são apagados durante a atualização. A opção do Windows para impedir suspensão da tela/computador durante a captura fica desligada por padrão e é independente da automação de cliques.

## Gravação opcional de sequência

**Gravar sequência de teste (75 s)** salva aproximadamente uma imagem por segundo por até 75 segundos, somente neste computador. Confira o recorte para não incluir dados pessoais. Essa captura serve para revisão e não confirma N+1 nem executa ordens.

## Atualização

Pare a captura, desligue a automação de cliques e feche o aplicativo. Na raiz do clone Git, atualize a branch:

```powershell
git pull origin arena/d4c07081-agency-agents
```
