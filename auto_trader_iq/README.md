# AUTO TRADER IQ — Etapa 3: simulação assistida

O aplicativo seleciona uma área da tela e reconhece, por OCR, etiquetas COMPRA/COMPRAR e VENDER/VENDA (também aceita BUY/SELL). Durante a captura, a interface muda para um painel compacto com uma prévia ao vivo da região capturada (com marcações OCR) e controles de armar/confirmar. A prévia usa a imagem já mascarada e o painel deve permanecer fora da região monitorada. Assim, o usuário confere o gráfico e interage sem restaurar a janela completa sobre ele. No fluxo manual, o sinal aparece após o fechamento de N e a entrada simulada só é registrada depois da confirmação de que N+1 nasceu.

**Por padrão, a abertura de N+1 é confirmada manualmente.** Em M1, só é permitida após HORA ATUAL avançar exatamente um minuto desde o armamento e durante os primeiros 30 s, calculados pelo relógio da plataforma; leituras ausentes, atrasadas ou com minutos pulados bloqueiam/descartam a entrada. O app ainda não identifica visualmente o nascimento da vela.

Há também um recurso experimental, desligado por padrão, para cliques automáticos em conta DEMO no Windows. Uma ativação mantém a automação ligada para sinais distintos, com limite configurável de **15 a 3.600 s (75 s por padrão)**, e permite no máximo uma tentativa por minuto M1 definido exclusivamente pelo relógio do Windows convertido para UTC−3. Esse relógio define tanto a virada usada na deduplicação quanto o segundo programado do clique. Para cada sinal OCR inequívoco, o app tenta no segundo M1 configurável **:00 a :30 (:05 por padrão)**; um sinal reconhecido antes aguarda esse segundo e um sinal reconhecido depois é descartado nessa vela. O prazo máximo armamento→clique segue configurável de **1 a 15 s (15 s por padrão)**; se a espera até o segundo fixo exceder o limite, o sinal é descartado sem clique. O OCR da HORA ATUAL da corretora não é usado como relógio de entrada DEMO. O OCR identifica o sinal; a idade do quadro não é uma referência temporal nem, sozinha, bloqueia o clique dentro do prazo controlado pelo Windows. Se uma nova leitura OCR deixar de mostrar o candidato armado, a tentativa é cancelada. Só tenta se o relógio local indicar **00–30 s**; após :30 descarta esse sinal sem clicar e aguarda outro sinal elegível. Não espera N+1, então o clique pode ocorrer ainda na vela N. Ao ativar, o app ancora o relógio de entrada na hora UTC do Windows e depois o avança monotonicamente durante a sessão. O fuso fixo UTC−3 não sincroniza o relógio do Windows com a corretora: confira a sincronização do Windows, pois os segundos podem divergir. A trava de repetição e o limite de uma tentativa são liberados quando o relógio do Windows UTC−3 avança para o próximo minuto; esse é o único relógio usado para a identidade M1 do DEMO. A HORA ATUAL OCR não participa dessa decisão. O Windows não sincroniza automaticamente com a corretora nem comprova visualmente qual candle está selecionado ou se o timeframe do app corresponde ao gráfico; mantenha o horário do Windows sincronizado e confira que o gráfico também está em M1. Um rótulo antigo que permaneça visível e passe pelo filtro de sinais recentes ainda pode ser considerado novamente após a virada do minuto do Windows. Essas travas são reiniciadas ao fechar o app. A identidade visual da vela não é verificada. O app não consegue verificar se a conta é DEMO, qual valor/expiração está configurado nem se a plataforma aceitou o clique. Se a janela estiver em conta real, o clique pode enviar uma ordem real. Não use em conta real.

## Arquitetura e decisões técnicas

- **Python 3.12+** e `tkinter` para a interface local.
- **MSS** captura somente a região selecionada; **Pillow** prepara e anota o preview. Áreas de exclusão opcionais são pintadas de preto imediatamente, antes do OCR, preview, snapshots e gravações; elas evitam reconhecer/registrar botões incluídos no mesmo retângulo para preservar HORA ATUAL. O teste de clique DEMO usa a API nativa do Windows apenas após habilitação explícita; durante a calibração ela só lê a posição do cursor.
- **pytesseract** chama o mecanismo Tesseract OCR instalado separadamente no Windows. O OCR roda a cada quadro da captura (aproximadamente duas vezes por segundo); se a passagem geral não reconhecer o relógio, leituras ampliadas alternativas são restritas ao rodapé/canto inferior direito e exigem o texto HORA ATUAL junto de HH:MM:SS.
- A confiança do Tesseract **não é uma probabilidade calibrada de acerto**. A palavra pode vir de controles da plataforma; mantenha a região restrita ao gráfico.
- Um filtro heurístico em Pillow localiza corpos de candles vermelhos/verdes e só libera OCR associado ao mais recente sinal nas duas barras mais à direita. Se não localizar pelo menos duas barras ou não conseguir associar o texto, bloqueia o candidato. Isso reduz sinais históricos, mas não prova identidade de candle.
- `SimulationWorkflow` impede mais de um sinal pendente, registra entradas no modo assistido quando o usuário confirma N+1 e bloqueia reutilização aproximada da mesma etiqueta durante a sessão. No modo manual, a interface avisa quando HORA ATUAL avança um minuto; o usuário ainda precisa conferir N+1 visualmente. A identidade espacial é uma proteção de teste, não equivale à identidade real da vela e não persiste após fechar o programa.
- O único módulo de mouse é o teste explícito de clique DEMO descrito acima: Windows, desligado por padrão, calibrações guardadas localmente e revalidadas por janela/geometria antes do uso, confirmação de conta DEMO a cada ativação e timeout configurável de 15–3.600 s. O limite é uma entrada por vela M1; o segundo fixo da entrada é configurável. Não verifica o tipo de conta, stake, expiração nem aceitação da ordem.

## Instalação no Windows

1. Instale Python 3.12 ou superior e confirme `python -m tkinter`.
2. Instale o **Tesseract OCR para Windows** separadamente. `pytesseract` é apenas o adaptador Python. O caminho padrão frequente é `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. No PowerShell, dentro da pasta `auto_trader_iq` do projeto (a que contém `requirements.txt`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

Crie essa venv uma vez e reutilize-a; não reinstale os pacotes a cada execução. O app detecta automaticamente o caminho padrão `C:\Program Files\Tesseract-OCR\tesseract.exe`. Se a instalação estiver em outro local, informe o executável no campo **Executável Tesseract** da janela; esse caminho e as demais preferências são salvos em `%LOCALAPPDATA%\AutoTraderIQ\config.json` ao alterar as opções, iniciar ou fechar o app. O OCR continua desligado até você habilitá-lo. No Windows, a opção **Manter tela/computador ativos durante a captura** fica desligada por padrão; quando marcada, solicita que o Windows não apague a tela nem suspenda o sistema enquanto a captura roda. O pedido é liberado ao parar a captura ou fechar o app. Isso não move o mouse nem impede um bloqueio manual da sessão, e pode aumentar o consumo de energia.

O comando `$env:TESSERACT_CMD = ...` vale apenas para a janela atual do PowerShell. Se preferir configurar essa variável permanentemente no usuário, execute uma vez e reinicie o PowerShell/app:

```powershell
[Environment]::SetEnvironmentVariable("TESSERACT_CMD", "C:\Program Files\Tesseract-OCR\tesseract.exe", "User")
```

## Atualizar no Windows

1. Desative os cliques DEMO, pare a captura e feche o aplicativo. As configurações e o CSV do histórico ficam em `%LOCALAPPDATA%\AutoTraderIQ` e não são substituídos pela atualização do código.
2. Abra o PowerShell na pasta raiz do clone Git (`agency-agents`) e atualize a branch do projeto:

   ```powershell
   git pull origin arena/d4c07081-agency-agents
   ```

3. Instale/atualize as dependências e teste a partir da pasta do app:

   ```powershell
   cd .\auto_trader_iq
   python -m pip install -r requirements.txt
   python -m unittest discover -s tests -v
   ```

4. No Windows, abra **Configurações → Hora e idioma → Data e hora**, deixe **Definir horário automaticamente** ativado e use **Sincronizar agora**. O modo DEMO usa o instante UTC do Windows na ativação e o converte para UTC−3; isso não garante sincronização exata com os segundos da corretora.
5. Inicie com `python -m auto_trader_iq.app`, confira conta DEMO, stake/expiração e alvos calibrados antes de ativar cliques.

## Executar e testar

Dentro da pasta `auto_trader_iq` do projeto:

```powershell
python -m auto_trader_iq.app
```

1. Selecione toda a área útil do gráfico onde as velas podem se deslocar; não recorte somente a vela atual. Exclua botões da corretora, janela do AUTO TRADER, banners e menus. Se não for possível excluir o painel de botões sem perder HORA ATUAL, use **Ocultar área dos botões do OCR/capturas…** para mascará-lo; a área fica preta antes do OCR, preview, captura salva e gravação de sequência. O filtro procura sinais apenas nas duas barras mais à direita.
2. Selecione o período do gráfico e inclua no recorte o relógio **HORA ATUAL** no canto inferior direito da plataforma. No fluxo manual, M1 usa a janela de 30 s após a virada; no clique DEMO, configure o prazo máximo armamento→clique entre 1 e 15 s (padrão 15 s) e o segundo fixo da entrada entre :00 e :30 (padrão :05). Sinais anteriores aguardam o segundo configurado; sinais que chegam depois dele são descartados na vela atual. Marque **Ativar OCR experimental COMPRA/VENDER** antes de iniciar a visualização. **Modo compacto ao monitorar** fica ligado por padrão.
3. Ao iniciar, o app vira um painel compacto com prévia ao vivo do gráfico, sinais OCR e controles. Arraste-o para uma área que não esteja dentro da região capturada; a miniatura é reduzida e as marcações dos sinais aparecem sobre a imagem já mascarada.
4. Clique **Configurações (pausar)** para parar a captura e voltar à janela completa. Para evitar que o app seja reconhecido como parte do gráfico, a região e o painel compacto não podem se sobrepor.
5. Confira os candidatos e selecione uma etiqueta na tabela. O rótulo e sua caixa no preview devem coincidir com a etiqueta do indicador.
6. Clique **Armar candidato selecionado**. O aplicativo fica pendente e não registra uma entrada ainda.
7. No modo assistido padrão, depois de observar que a próxima vela N+1 nasceu, clique **Confirmar abertura da próxima vela**. O resultado é simulado e acrescentado ao histórico local `simulation_history.csv`. Use **Cancelar** para descartar o pendente; a mesma etiqueta não será rearmada naquela sessão.

### Teste experimental de clique DEMO no Windows

Use exclusivamente em conta DEMO. O app não consegue distinguir DEMO de REAL; em conta real, o clique pode enviar uma ordem. Antes de cada ativação, confira manualmente a conta e os valores/expiração já configurados na plataforma — o AUTO TRADER não lê nem altera esses parâmetros.

1. Com o app pausado e a plataforma visível, na janela completa use **Calibrar COMPRAR** e **Calibrar VENDER**. Em cada etapa, a janela do app some por 5 s: mova o cursor ao centro do botão correto e não clique. A calibração registra a posição do cursor e identifica a janela que está sob o ponto do botão, sem clicar. Se o botão estiver dentro do recorte, marque uma área de ocultação grande o bastante para cobrir todo o botão e uma margem ao redor. Os alvos BUY/SELL, ponto neutro e áreas ocultadas são salvos localmente junto das configurações. Na próxima inicialização, o app só restaura essas calibrações se a disposição dos monitores for a mesma; antes de autorizar clique/movimento, revalida a identidade e o retângulo da janela da corretora. Se a plataforma for reiniciada, movida/redimensionada ou a disposição das telas mudar, traga-a à frente e calibre novamente. Se quiser o movimento opcional sem clique, habilite a opção separadamente e escolha uma área vazia da mesma janela, afastada pelo menos 100 px dos botões; o app alternará dois pontos adjacentes.
2. Inicie a captura M1 com OCR. Habilite **Ativar cliques DEMO…** e confirme o aviso, somente após conferir novamente a conta DEMO, stake e expiração.
3. Configure o limite de ativação contínua (15–3.600 s; padrão 75 s) e o prazo máximo após armar o sinal (1–15 s; padrão 15 s). No modo DEMO, a fonte temporal é o relógio do Windows convertido para UTC−3; não é a leitura HORA ATUAL da corretora e pode divergir em segundos se o Windows não estiver sincronizado. O OCR continua obrigatório para reconhecer o sinal, mas a idade do quadro não impõe um timeout separado ao clique. Se houver exatamente um candidato OCR filtrado, o app o arma sozinho e programa o clique para o segundo fixo configurado; se uma nova leitura OCR deixar de mostrar esse candidato, cancela a tentativa. Se o sinal aparecer depois do segundo fixo, descarta-o nesta vela. O prazo armamento→clique limita também a espera até o segundo fixo. Só tenta se o relógio Windows UTC−3 ainda estiver em 00–30 s. Se passar de :30, descarta o sinal sem enviar entrada. Não espera a virada de minuto, então a entrada pode ocorrer ainda durante N. Uma ativação pode tratar sinais novos, mas não faz mais de uma tentativa por vela M1; encerra ao atingir o timeout, ao parar manualmente ou em caso de leitura/execução insegura. Use **Parar cliques DEMO** para interrompê-la.
4. Opcional: marque **Movimentar cursor sem clicar após inatividade (somente DEMO)** e ajuste o intervalo (30–600 s; padrão 60 s). O recurso só atua durante uma ativação DEMO explicitamente autorizada, depois do intervalo sem entrada do usuário, e somente se os pontos neutros ainda estiverem sobre a janela calibrada da corretora e afastados dos botões. Ele alterna entre dois pontos próximos sem enviar cliques; o cursor mudará de posição e pode produzir efeitos de hover. Desmarque a opção ou pare a automação para interrompê-lo.

Este é um ensaio de integração do mouse, **não uma confirmação automática confiável da vela**: o app não verifica visualmente a identidade da vela nem se a plataforma aceitou a ordem. Durante a calibração, registra também a janela presente sob o ponto do botão; antes de clicar, verifica se essa mesma janela continua no topo naquele ponto. Se outra janela a cobrir, traga a plataforma para frente e calibre novamente. No modo manual, relógio HORA ATUAL OCR ausente/desatualizado bloqueia a confirmação; no modo DEMO, somente o relógio Windows UTC−3 determina a janela temporal, sem timeout separado por idade do OCR. Uma nova leitura OCR que não mostre o candidato armado ainda cancela a tentativa. Em ambos os modos, erro de clique encerra o teste sem tentativa de repetição. Verifique a plataforma após o clique.

## Histórico local de simulações

O aplicativo mantém `%LOCALAPPDATA%\AutoTraderIQ\simulation_history.csv` no Windows (ou `~/.auto_trader_iq/simulation_history.csv` em outros sistemas). O CSV local registra metadados de sinais armados, viradas de minuto observadas, entradas simuladas, cliques DEMO, cancelamentos e expirações: horário da fonte usada, origem do relógio, evento, período, direção, texto OCR, confiança do sinal, posição do rótulo, segundos decorridos em M1 e confiança do relógio OCR quando aplicável. Entradas manuais continuam usando a HORA ATUAL OCR da plataforma. Cliques DEMO registram explicitamente `windows_utc_minus_3`, o relógio local ao armar e o delta inteiro entre armar e clicar; o campo genérico `entry_delay_seconds` não representa sincronização nem mede frações de segundo. Registros antigos usam os campos legados e não têm origem do relógio identificada. A tabela mostra as 20 entradas simuladas/cliques DEMO mais recentes após reabrir o app. Use **Salvar todas as entradas…** para exportar todas as entradas a outro CSV. **Limpar log…** apaga a tabela e exclui permanentemente o CSV local após confirmação explícita; exporte antes se quiser guardar uma cópia. A limpeza não remove a trava de sinal da sessão atual. O app ainda não calcula WIN/LOSS; um clique enviado não prova aceitação nem resultado da ordem.

Esse histórico não contém imagens, não é transmitido e não gera ordens. Falhas na gravação são avisadas na interface, mas não interrompem a simulação assistida. A gravação separada de sequências continua opt-in, limitada a 75 segundos e salva imagens localmente, conforme descrito abaixo; qualquer área de exclusão selecionada é pintada de preto antes de OCR, preview, snapshot ou gravação.

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
