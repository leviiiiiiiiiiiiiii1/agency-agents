# AUTO TRADER IQ — OCR e cliques automáticos

Aplicativo local que captura uma região da tela, reconhece etiquetas COMPRA/COMPRAR, VENDER/VENDA, BUY e SELL por OCR e mostra candidatos para revisão. Também mantém um fluxo separado de simulação manual e oferece **cliques automáticos opcionais**, habilitados pelo usuário em cada sessão.

## Automação de cliques

Os cliques automáticos ficam desligados até serem ativados explicitamente. No Windows, o usuário calibra os alvos COMPRAR e VENDER e escolhe o segundo fixo entre `:00` e `:30` (padrão `:05`). Um sinal reconhecido antes desse segundo é armado e aguarda o horário configurado; um sinal reconhecido depois é descartado naquela vela. Não há prazo individual entre armar o sinal e o clique. A ativação contínua pode ser configurada entre **15 e 28.800 segundos (8 horas; 75 segundos por padrão)**, com no máximo uma tentativa por minuto M1. Uma nova leitura OCR que não mostre mais a etiqueta armada cancela a tentativa.

O relógio do Windows convertido para UTC−3 define a janela M1 da automação. Na ativação, o app ancora o relógio no instante UTC do Windows e o avança monotonicamente durante a sessão. Ele não é sincronizado com a corretora e pode divergir em segundos; a leitura OCR de HORA ATUAL não determina o horário do clique. A captura/prévia atualiza até 4 vezes por segundo; OCR e contexto visual rodam em workers separados para que uma leitura OCR lenta não atrase o painel de contexto. Para capturas grandes, o OCR evita ampliar a imagem inteira; quadros OCR cuja análise leve mais de 1,5 s continuam sendo descartados para evitar sinais defasados. Isso não cria um prazo individual entre armar o sinal e o segundo de clique configurado. Se o rótulo desaparecer numa nova leitura, a tentativa pendente é cancelada. A automação não espera N+1 e pode clicar ainda durante a vela N. As travas contra repetição valem durante a sessão e são reiniciadas ao fechar o app; um rótulo antigo que continue visível pode ser reconsiderado após a virada do minuto.

O app não verifica a conta selecionada, o valor, a expiração, a identidade visual da vela ou se a plataforma aceitou o clique. **Um clique pode enviar uma ordem real.** Antes de ativar, confira a conta e todos os parâmetros diretamente na plataforma. Não use a automação se não puder confirmar a configuração correta. Na calibração, a janela e a posição dos botões são registradas e revalidadas antes do clique; se outra janela cobrir os alvos, a automação é bloqueada até que a plataforma seja trazida à frente e os botões sejam recalibrados.

O movimento opcional do cursor sem clique é uma configuração separada: ocorre apenas após inatividade, entre pontos neutros calibrados e durante uma ativação explícita. Pode alterar efeitos de foco/hover da plataforma.

## Simulação manual e OCR

A simulação manual continua disponível: o usuário arma um candidato e confirma visualmente que a vela N+1 nasceu. Em M1, a confirmação usa a leitura HORA ATUAL da plataforma, exige avanço de exatamente um minuto desde o armamento e fica limitada aos primeiros 30 segundos. Leituras ausentes, atrasadas ou com minutos pulados bloqueiam a confirmação. A entrada resultante é registrada como **SIMULADA** e não é enviada à corretora.

A confiança do Tesseract não é uma probabilidade calibrada. Quando a leitura normal não encontra etiquetas, o app faz uma segunda leitura OCR isolando pixels verdes/vermelhos; candidatos desse recurso só passam quando a cor confirma COMPRA/BUY (verde) ou VENDER/SELL (vermelho). A leitura normal também tenta aceitar texto com até um caractere de erro ou confiança até 20 pontos abaixo do limite, mas somente quando a cor da etiqueta confirma a direção; conflitos de cor descartam o candidato. Texto exato de alta confiança sem cor confiável continua aceito. A associação geométrica tenta localizar barras recentes, mas não comprova a identidade da vela.

No painel **Contexto do gráfico**, calibre explicitamente a paleta da captura antes de interpretar direção. A configuração fica vinculada à região/layout; se eles mudarem, a calibração deixa de valer. Para o gráfico Binarium mostrado na validação do usuário, a opção informada foi **Verde = alta / branca = baixa**. Sem calibração correspondente, velas claras não são tratadas como alta nem baixa e o contexto direcional permanece indisponível. O contexto usa apenas as cores mapeadas e continua sendo heurístico: “fluxo” significa movimento de preço visível, não dados de book/negócios; zoom, tema e layout podem afetar a classificação.

Quando os cliques automáticos estão ativados, há uma trava direcional adicional: **COMPRA só é armada/enviada em fluxo comprador; VENDER só em fluxo vendedor**. Além da geometria das velas, duas ou mais velas distintas entre as 12 recentes com etiquetas OCR COMPRA/BUY (ou VENDER/SELL) associadas contam como fluxo na respectiva direção; várias etiquetas na mesma vela contam uma vez. Se ambas as direções atingirem esse critério, o contexto fica conflitante e bloqueia cliques. Contexto ausente, incompatível ou com mais de 1,5 s bloqueia o armamento; se deixar de ser compatível ou ficar desatualizado enquanto o clique aguarda o segundo configurado, o sinal pendente é cancelado sem clique. A etiqueta isolada nunca autoriza um clique automático. A simulação manual permanece separada desta trava.

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

## Journal transacional e recuperação

O journal SQLite fica em `%LOCALAPPDATA%\AutoTraderIQ\opportunities.sqlite3` no Windows (ou em `~/.auto_trader_iq` nos outros sistemas). O schema 3 preserva os IDs/eventos existentes e registra sessões, quadros independentes aceitos/rejeitados, conclusões/falhas de OCR, estados de sinal, decisões e eventos de simulação. A chave de idempotência evita eventos duplicados em retries; triggers impedem alterar/apagar eventos já gravados. A tabela `opportunities` é uma projeção atualizável; o log append-only é `opportunity_events`.

Antes de migrar um banco existente, o inicializador cria uma cópia consistente pelo mecanismo de backup do SQLite, com nome `opportunities.backup-v3-<UTC>.sqlite3`. Na inicialização, `quick_check`, chaves estrangeiras, sessões de captura sem encerramento e execuções sem estado final são inspecionados. Sessões órfãs só podem ser marcadas como interrompidas depois de confirmação explícita de que a captura não está ativa; execuções incertas nunca são repetidas automaticamente. A migração foi verificada em banco local de teste e no Windows do usuário; sessões órfãs e motivos de falha OCR ainda exigem revisão.

### Diagnóstico de latência do OCR

Cada quadro lido termina em `OCR_COMPLETED` ou `OCR_FAILED`. O motivo do descarte é explícito: `STALE_FRAME` quando o quadro passou de `1,5 s` até a análise terminar, `CAPTURE_QUALITY_INVALID` quando a captura perdeu qualidade, e ambos os sinalizadores aparecem no payload se as duas causas ocorrerem. Os mesmos eventos trazem `ocr_timings` com `full_pass_seconds`, `color_fallback_seconds`, `color_fallback_passes`, `clock_crop_seconds`, `clock_crop_passes`, `candle_detection_seconds`, `upscale_factor` e `total_seconds`. Esses números existem para localizar o gargalo — o limite de idade continua valendo e quadro defasado nunca gera sinal nem clique.

Cada evento de OCR também traz quanto o quadro **entregou**, não só quanto custou: `ocr_yield` informa `raw_candidate_count`, `recent_candidate_count`, `bar_count`, `clock_readable`, `color_rejected_count` e `label_counts`. Isso separa "o quadro tinha rótulos e chegou tarde" de "o quadro não tinha nada legível", que exigem correções diferentes.

A faixa do relógio no rodapé é a etapa mais cara do OCR e roda em executor próprio, em paralelo à leitura de rótulos e encadeada sem intervalo (assim que uma leitura termina, a próxima começa). Ela deixa de somar segundos ao caminho crítico dos sinais. O limite de 1,5 s e o bloqueio por relógio velho permanecem iguais: a leitura muda de lugar, não de critério, e um quadro de rótulos descartado não apaga a última leitura válida do relógio.

Se o recorte do rodapé voltar vazio repetidamente, o app registra um evento `CLOCK_PROBE` a cada 20 tentativas sem leitura: ele procura horários no quadro inteiro e grava apenas os horários encontrados, as palavras de relógio e as posições relativas. Nomes de ativo, preços e demais textos do gráfico não são registrados — só contados. Isso localiza o relógio quando o layout muda, sem capturar dados financeiros.

A detecção de velas também registra por que aceitou ou descartou barras, dentro de `ocr_timings.candle_detection`: colunas dominantes por cor, número de trechos, barras estreitas, barras curtas/esparsas e quantas sobraram depois da calibração de paleta. Assim "0 velas" deixa de ser ambíguo entre cor não reconhecida e geometria insuficiente.

Quando nenhum rótulo é associado, o app nomeia a causa em vez de dizer apenas "desalinhado": `PALETTE_NOT_CALIBRATED` (paleta não calibrada — a direção das cores não é presumida), `INSUFFICIENT_BARS`, `COLOR_CONFLICT`, `LABELS_HISTORICAL` ou `NO_LABELS`. O mesmo código vai para o journal em `association.code`, junto de `raw_count`, `recent_count`, `bar_count` e `palette_calibrated`.

O filtro de associação é estrito por decisão do operador: só a última vela e a imediatamente anterior contam. Rótulo em vela mais antiga continua registrado no journal, mas nunca vira candidato.

## Elegibilidade estratégica

`eligibility.py` não define estratégia: garante que nada seja elegível sem critérios declarados. `EligibilityCriteria` tem todos os campos opcionais e **ausente significa não definido**, então o resultado padrão é `CRITERIA_UNDEFINED`. Com critérios completos, a avaliação devolve `ELIGIBLE_FOR_REVIEW` ou `NOT_ELIGIBLE` com o motivo, e medida ausente (confiança, idade do rótulo em velas) bloqueia em vez de ser presumida.

Critérios ficam em `config.json`, na chave `eligibility`, e são validados antes de uso: faixa 0–100, direções existentes, `min_bars` acima do piso do contexto (6), `max_label_age_bars` até 1 (limite do filtro de associação), booleanos reais e recusa de contradições — alinhamento sem exigir direção, ou exigir direção com paleta não calibrada. `min_confidence` abaixo do piso do OCR é **erro**, não escolha conservadora, porque não filtraria nada.

O perfil recomendado para iniciar é `equilibrada`: `min_confidence` 80, BUY e SELL, paleta calibrada obrigatória, `min_bars` 8, idade máxima 1 vela, contexto direcional exigido e alinhamento **não** exigido. `conservadora` e `seletiva` existem em `PROFILES` como referência.

Configuração inválida ou contraditória não vira "sem filtro": os critérios são esvaziados, a decisão fica bloqueada e o motivo aparece no painel. Na abertura de cada sessão, `CAPTURE_SESSION_STARTED` grava os critérios, o hash e os problemas encontrados; cada quadro grava `eligibility.code` e `criteria_hash`. Mudar parâmetros depois não altera eventos já gravados.

## Classificação do momento (A / B / C / NO TRADE)

`opportunity_grade.py` classifica a oportunidade usando apenas o que a captura permite medir: idade do rótulo em velas, **corpo da vela de setup** (a anterior à seta — a seta marca a vela de entrada, e medir a própria seta descreveria o que já aconteceu) em relação à mediana das últimas 10, distância percentual até o nível contrário dentro da faixa de 20 velas, posição do fechamento no próprio candle e regime de contexto. **RSI, histograma MACD e distância à EMA20 não são legíveis por pixel** e aparecem em `unmeasured` — a classificação nunca finge tê-los considerado.

Regras padrão: contexto lateral ou rótulo acima de 2 velas → `NO_TRADE`; corpo acima de 2× a mediana, preço a menos de 15% do nível contrário, fechamento colado no extremo ou sinal contra o contexto → `C`; rótulo com 2 velas de idade ou corpo fora da faixa ideal (fraco ou acima de 1,5×) → `B`; rótulo na última vela fechada (idade ≤ 1, porque a vela em formação fica à direita da seta), corpo entre 0,4× e 1,5× a mediana e folga do nível → `A`. Limiares ficam em `config.json` na chave `grading`, são validados e voltam ao padrão declarado quando inválidos. `grading_version` registra a versão dos padrões: ao carregar uma configuração antiga, o valor `fresh_age_bars = 0` — que a tela nunca produz — é corrigido para 1, com aviso no painel; qualquer outro valor escolhido à mão é preservado. A classe, o hash dos limiares e as medidas usadas vão para o journal em `grade`.

### Relatório de calibração

Os limiares acima são valores iniciais, **não calibrados**. Para calibrar com medição, e não com opinião:

```powershell
python -m auto_trader_iq.grade_report --sweep max_body_vs_median_b=2,2.5,3
```

Sem `--db`, o comando procura o journal do próprio app em `%LOCALAPPDATA%\AutoTraderIQ\opportunities.sqlite3` e diz onde olhou se não encontrar. `--db` continua disponível para apontar outro arquivo. Rode a partir da pasta `auto_trader_iq` do repositório, com o mesmo Python que abre o app.

O comando abre o banco em **modo somente-leitura** e mostra: cobertura de cada medida, distribuição das classes, percentis de corpo/distância/fechamento, idade dos rótulos, regime de contexto, motivos de bloqueio, séries de rótulo recente e rastros de posição (a identidade de rastro usa posição em pixels e primeiro avistamento, então rolagem do gráfico fragmenta o mesmo rótulo — rastro não é contagem de sinais) o efeito de variar um limiar sobre os quadros já gravados e a separação por hash de limiares, para não misturar quadros de versões antigas, o método de medição da geometria (`setup_candle_v1` mede a vela anterior à seta; registros sem essa marca não são comparáveis) e a geometria do rótulo — espaçamento entre velas e quantas velas há à direita dele, que é o que explica a idade observada. Quando a idade mínima observada for maior que `fresh_age_bars`, o relatório avisa que a classe A é inalcançável — sem alterar nada por conta própria. Use `--json` para exportar.

Cada quadro é classificado como `NO_LABEL` (nenhum rótulo na tela), `LABEL_OUTSIDE_WINDOW` (rótulo existe, mas fora das duas últimas velas) ou `A/B/C/NO_TRADE`. Registros anteriores separam os dois primeiros casos como `NO_CANDIDATE`; a partir de `b905d15`+motivos, a distinção aparece.

O relatório **não calcula taxa de acerto**. Os quadros não têm desfecho vinculado porque nenhuma ordem é enviada; qualquer número nesse sentido seria inventado. Amostra abaixo de 200 quadros com candidato não sustenta mudança de limiar.

O CSV legado em `%LOCALAPPDATA%\AutoTraderIQ\simulation_history.csv` continua preservado e serve à compatibilidade/exportação; ele não é apagado nem substituído pelo journal.

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
