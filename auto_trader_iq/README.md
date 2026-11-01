# AUTO TRADER IQ — Etapa 3: simulação assistida

O aplicativo seleciona uma área da tela e reconhece, por OCR, etiquetas COMPRA/COMPRAR e VENDER/VENDA (também aceita BUY/SELL). Durante a captura, a interface muda para um painel compacto com controles de armar/confirmar, que pode ser movido para fora da região monitorada. Assim, o usuário interage sem restaurar a janela completa sobre o gráfico. A simulação segue o fluxo: o sinal aparece após o fechamento de N; a entrada de teste só é registrada depois da confirmação de que N+1 nasceu.

**Por padrão, a abertura de N+1 é confirmada manualmente.** Em M1, só é permitida após HORA ATUAL avançar exatamente um minuto desde o armamento e durante os primeiros 30 s, calculados pelo relógio da plataforma; leituras ausentes, atrasadas ou com minutos pulados bloqueiam/descartam a entrada. O app ainda não identifica visualmente o nascimento da vela.

Há também um recurso experimental, desligado por padrão, para testar **um clique por ativação (no máximo 75 s)** em conta DEMO no Windows. Ele arma automaticamente somente um candidato OCR inequívoco, espera um avanço de um minuto e clica no alvo COMPRAR/VENDER calibrado se o relógio indicar M1 +0–30 s. Esse avanço do relógio é apenas uma aproximação de N+1 — não prova a identidade/nascimento da vela. O app não consegue verificar se a conta é DEMO, qual valor/expiração está configurado nem se a plataforma aceitou o clique. Se a janela estiver em conta real, o clique pode enviar uma ordem real. Não use em conta real.

## Arquitetura e decisões técnicas

- **Python 3.12+** e `tkinter` para a interface local.
- **MSS** captura somente a região selecionada; **Pillow** prepara e anota o preview. **PyAutoGUI** só é carregado para o teste de clique DEMO explicitamente habilitado; durante a calibração ele apenas lê a posição do cursor.
- **pytesseract** chama o mecanismo Tesseract OCR instalado separadamente no Windows. O OCR roda aproximadamente uma vez por segundo; se a passagem geral não reconhecer o relógio, leituras ampliadas alternativas são restritas ao rodapé/canto inferior direito e exigem o texto HORA ATUAL junto de HH:MM:SS.
- A confiança do Tesseract **não é uma probabilidade calibrada de acerto**. A palavra pode vir de controles da plataforma; mantenha a região restrita ao gráfico.
- Um filtro heurístico em Pillow localiza corpos de candles vermelhos/verdes e só libera OCR associado ao mais recente sinal nas duas barras mais à direita. Se não localizar pelo menos duas barras ou não conseguir associar o texto, bloqueia o candidato. Isso reduz sinais históricos, mas não prova identidade de candle.
- `SimulationWorkflow` impede mais de um sinal pendente, registra entradas no modo assistido quando o usuário confirma N+1 e bloqueia reutilização aproximada da mesma etiqueta durante a sessão. No modo manual, a interface avisa quando HORA ATUAL avança um minuto; o usuário ainda precisa conferir N+1 visualmente. A identidade espacial é uma proteção de teste, não equivale à identidade real da vela e não persiste após fechar o programa.
- O único módulo de mouse é o teste explícito de clique DEMO descrito acima: Windows, desligado por padrão, alvo calibrado a cada inicialização, confirmação de conta DEMO a cada ativação e no máximo um clique por ativação, que expira em 75 s. Não verifica o tipo de conta, stake, expiração, aceitação da ordem ou sobreposição de janelas da corretora.

## Instalação no Windows

1. Instale Python 3.12 ou superior e confirme `python -m tkinter`.
2. Instale o **Tesseract OCR para Windows** separadamente. `pytesseract` é apenas o adaptador Python. O caminho padrão frequente é `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. No PowerShell, dentro da pasta `auto_trader_iq` do projeto (a que contém `requirements.txt`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

Se a venv já estiver ativa, não crie outra. Caso o Tesseract não esteja no PATH, configure antes de iniciar:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Executar e testar

Dentro da pasta `auto_trader_iq` do projeto:

```powershell
python -m auto_trader_iq.app
```

1. Selecione toda a área útil do gráfico onde as velas podem se deslocar; não recorte somente a vela atual. Exclua botões da corretora, janela do AUTO TRADER, banners e menus. O filtro procura sinais apenas nas duas barras mais à direita.
2. Selecione o período do gráfico (M1 para a janela de 30 s) e inclua no recorte o relógio **HORA ATUAL** no canto inferior direito da plataforma. Marque **Ativar OCR experimental COMPRA/VENDER** antes de iniciar a visualização. **Modo compacto ao monitorar** fica ligado por padrão.
3. Ao iniciar, o app vira um painel pequeno e continua na frente para permitir armar/confirmar. Arraste-o para uma área que não esteja dentro da região capturada; monitore o gráfico sem que o painel cubra os rótulos.
4. Clique **Configurações (pausar)** para parar a captura e voltar à janela completa. Para evitar que o app seja reconhecido como parte do gráfico, a região e o painel compacto não podem se sobrepor.
5. Confira os candidatos e selecione uma etiqueta na tabela. O rótulo e sua caixa no preview devem coincidir com a etiqueta do indicador.
6. Clique **Armar candidato selecionado**. O aplicativo fica pendente e não registra uma entrada ainda.
7. No modo assistido padrão, depois de observar que a próxima vela N+1 nasceu, clique **Confirmar abertura da próxima vela**. O resultado é simulado e acrescentado ao histórico local `simulation_history.csv`. Use **Cancelar** para descartar o pendente; a mesma etiqueta não será rearmada naquela sessão.

### Teste experimental de clique DEMO no Windows

Use exclusivamente em conta DEMO. O app não consegue distinguir DEMO de REAL; em conta real, o clique pode enviar uma ordem. Antes de cada ativação, confira manualmente a conta e os valores/expiração já configurados na plataforma — o AUTO TRADER não lê nem altera esses parâmetros.

1. Com o app pausado e a plataforma visível, na janela completa use **Calibrar COMPRAR** e **Calibrar VENDER**. Em cada etapa, a janela do app some por 5 s: mova o cursor ao centro do botão correto e não clique. A calibração lê apenas a posição atual do cursor. Os pontos devem ficar fora do recorte do gráfico e não são salvos entre inicializações; recalibre ao abrir o app ou se a plataforma/telas mudarem de posição.
2. Inicie a captura M1 com OCR. Habilite **Ativar cliques DEMO…** e confirme o aviso, somente após conferir novamente a conta DEMO, stake e expiração.
3. Se houver exatamente um candidato OCR filtrado, o app o arma sozinho. Ao observar o próximo avanço de exatamente um minuto em HORA ATUAL, ele tenta um único clique no botão da direção do sinal, desde que a leitura continue fresca e esteja em M1 +0–30 s. A ativação encerra após esse clique ou após 75 s sem clique; é possível parar antes pelo botão **Parar cliques DEMO** ou **Cancelar**.

Este é um ensaio de integração do mouse, **não uma confirmação automática confiável de N+1**: a virada do relógio serve apenas como aproximação, e o app não verifica visualmente a identidade da vela nem se a plataforma aceitou a ordem. Se houver leitura ambígua, atraso, minuto pulado, alvo coberto ou erro de clique, o app bloqueia ou encerra o teste sem tentar repetir. Verifique a plataforma após o clique.

## Histórico local de simulações

O aplicativo mantém `%LOCALAPPDATA%\AutoTraderIQ\simulation_history.csv` no Windows (ou `~/.auto_trader_iq/simulation_history.csv` em outros sistemas). O CSV append-only registra metadados de sinais armados, viradas de minuto observadas, entradas simuladas, cliques DEMO, cancelamentos e expirações: HORA ATUAL quando legível, evento, período, direção, texto OCR, confiança, posição do rótulo, segundos decorridos em M1 e confiança do relógio. A tabela mostra as 20 entradas simuladas/cliques DEMO mais recentes após reabrir o app.

Esse histórico não contém imagens, não é transmitido e não gera ordens. Falhas na gravação são avisadas na interface, mas não interrompem a simulação assistida. A gravação separada de sequências continua opt-in, limitada a 75 segundos e salva imagens localmente, conforme descrito abaixo.

## Validação da virada M1 com capturas reais

Durante uma visualização M1 com OCR ativo, o botão **Gravar sequência de teste (75 s)** fica disponível também no painel compacto. Inicie a gravação cerca de 20–30 s antes da próxima virada de minuto. Ela salva aproximadamente uma imagem por segundo por até 75 s e encerra sozinha; também pode ser parada manualmente. Parar a visualização ou fechar o app encerra a gravação de forma segura.

Após confirmação explícita, as imagens da região selecionada e um `manifest.csv` (hora e confiança do OCR, trecho diagnóstico da leitura HORA ATUAL, contagem heurística de candles e candidatos OCR) são gravados somente em `%LOCALAPPDATA%\AutoTraderIQ\sequences`. A aplicação não envia esses arquivos pela rede. Como as imagens podem conter informação pessoal, confira o recorte e inspecione os arquivos antes de compartilhar. O registro é apenas para validação: não confirma N+1 automaticamente e não envia ordens.

### Verificar apenas a virada do relógio

Com uma sequência gravada, rode a verificação local do `manifest.csv` no PowerShell, dentro da pasta `auto_trader_iq` do projeto:

```powershell
$seq = Get-ChildItem "$env:LOCALAPPDATA\AutoTraderIQ\sequences" -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
python -m auto_trader_iq.validate_sequence $seq.FullName
```

O relatório considera leituras adjacentes com confiança OCR mínima de 70% e informa se observou o relógio avançar exatamente um minuto. Lê somente o CSV — não abre imagens, não interpreta sinais/candles e não confirma N+1. Código de saída 0 indica virada observada; 1, nenhuma virada confirmada no manifesto; 2, erro de leitura/validação. Se não houver virada observada, confira a gravação e o recorte antes de qualquer outra conclusão.

Testes unitários (não precisam de tela gráfica nem do mecanismo Tesseract):

```powershell
python -m unittest discover -s tests -v
```

## Limitações / próxima etapa

- O filtro de barras é uma heurística baseada em cor/largura/altura e mantém apenas candidatos alinhados às duas barras mais recentes; zoom, temas, doji, velas muito estreitas, rolagem e overlays podem causar falso bloqueio ou associação errada. Confira visualmente cada candidato; a seleção manual continua necessária.
- A confirmação da abertura da próxima vela é manual porque ainda não foi validado um método visual confiável para detectar vela/candle identity, rolagem do gráfico e período configurado.
- O histórico local é um registro técnico, não mede lucro, não verifica aceitação de ordem e não usa dados de mercado. A prevenção de duplicatas continua limitada à sessão atual.
- Antes de automatizar essa confirmação, será necessário validar capturas sequenciais reais com o ativo e o período gráfico usados. Em qualquer incerteza, a ação segura é não simular/operar.
- Operações financeiras envolvem risco e podem estar sujeitas às regras da plataforma. Execução real continua fora do escopo.
