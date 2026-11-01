# AUTO TRADER IQ — Etapa 3: simulação assistida

O aplicativo seleciona uma área da tela e reconhece, por OCR, etiquetas COMPRA/COMPRAR e VENDER/VENDA (também aceita BUY/SELL). Durante a captura, a interface muda para um painel compacto com controles de armar/confirmar, que pode ser movido para fora da região monitorada. Assim, o usuário interage sem restaurar a janela completa sobre o gráfico. A simulação segue o fluxo: o sinal aparece após o fechamento de N; a entrada de teste só é registrada depois da confirmação de que N+1 nasceu.

**A abertura de N+1 é confirmada manualmente nesta etapa.** Em M1, a confirmação só é permitida nos primeiros 30 s após a abertura, usando OCR do timer da plataforma próximo ao rótulo “HORA”; se o timer não puder ser lido com confiança, a confirmação fica bloqueada. O programa ainda não detecta automaticamente o nascimento da vela. Nada clica, envia ordem ou interage com a corretora; o fluxo é uma simulação assistida e não valida sinal nem resultado financeiro.

## Arquitetura e decisões técnicas

- **Python 3.12+** e `tkinter` para a interface local.
- **MSS** captura somente a região selecionada; **Pillow** prepara e anota o preview.
- **pytesseract** chama o mecanismo Tesseract OCR instalado separadamente no Windows. O OCR roda aproximadamente uma vez por segundo.
- A confiança do Tesseract **não é uma probabilidade calibrada de acerto**. A palavra pode vir de controles da plataforma; mantenha a região restrita ao gráfico.
- Um filtro heurístico em Pillow localiza corpos de candles vermelhos/verdes e só libera OCR associado ao mais recente sinal nas duas barras mais à direita. Se não localizar pelo menos duas barras ou não conseguir associar o texto, bloqueia o candidato. Isso reduz sinais históricos, mas não prova identidade de candle.
- `SimulationWorkflow` impede mais de um sinal pendente, registra entrada somente quando o usuário confirma a próxima vela e bloqueia reutilização aproximada da mesma etiqueta durante a sessão. A identidade espacial é uma proteção de teste, não equivale à identidade real da vela e não persiste após fechar o programa.
- Não há módulo de automação de mouse/teclado, conexão com corretora ou envio de ordens.

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
2. Selecione o período do gráfico (M1 para a janela de 30 s) e inclua no recorte o timer da plataforma ao lado de “HORA DE COMPRA”. Marque **Ativar OCR experimental COMPRA/VENDER** antes de iniciar a visualização. **Modo compacto ao monitorar** fica ligado por padrão.
3. Ao iniciar, o app vira um painel pequeno e continua na frente para permitir armar/confirmar. Arraste-o para uma área que não esteja dentro da região capturada; monitore o gráfico sem que o painel cubra os rótulos.
4. Clique **Configurações (pausar)** para parar a captura e voltar à janela completa. Para evitar que o app seja reconhecido como parte do gráfico, a região e o painel compacto não podem se sobrepor.
5. Confira os candidatos e selecione uma etiqueta na tabela. O rótulo e sua caixa no preview devem coincidir com a etiqueta do indicador.
6. Clique **Armar candidato selecionado**. O aplicativo fica pendente e não registra uma entrada ainda.
7. Somente depois de observar que a próxima vela N+1 nasceu, clique **Confirmar abertura da próxima vela**. O resultado é marcado como entrada simulada em memória. Use **Cancelar** para descartar o pendente; a mesma etiqueta não será rearmada naquela sessão.

Testes unitários (não precisam de tela gráfica nem do mecanismo Tesseract):

```powershell
python -m unittest discover -s tests -v
```

## Limitações / próxima etapa

- O filtro de barras é uma heurística baseada em cor/largura/altura e mantém apenas candidatos alinhados às duas barras mais recentes; zoom, temas, doji, velas muito estreitas, rolagem e overlays podem causar falso bloqueio ou associação errada. Confira visualmente cada candidato; a seleção manual continua necessária.
- A confirmação da abertura da próxima vela é manual porque ainda não foi validado um método visual confiável para detectar vela/candle identity, rolagem do gráfico e período configurado.
- O histórico da simulação é apenas em memória; não mede lucro, não verifica aceitação de ordem e não usa dados de mercado.
- Antes de automatizar essa confirmação, será necessário validar capturas sequenciais reais com o ativo e o período gráfico usados. Em qualquer incerteza, a ação segura é não simular/operar.
- Operações financeiras envolvem risco e podem estar sujeitas às regras da plataforma. Execução real continua fora do escopo.
