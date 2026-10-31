# AUTO TRADER IQ — Etapa 3: simulação assistida

O aplicativo seleciona uma área da tela e reconhece, por OCR, etiquetas COMPRA/COMPRAR e VENDER/VENDA (também aceita BUY/SELL). A simulação implementa o fluxo informado: o sinal aparece após o fechamento de N; a entrada de teste só é registrada depois da confirmação de que N+1 nasceu.

**A abertura de N+1 é confirmada manualmente nesta etapa.** O programa ainda não determina automaticamente a identidade/abertura da vela. Nada clica, envia ordem ou interage com a corretora; o fluxo é uma simulação assistida e não valida sinal nem resultado financeiro.

## Arquitetura e decisões técnicas

- **Python 3.12+** e `tkinter` para a interface local.
- **MSS** captura somente a região selecionada; **Pillow** prepara e anota o preview.
- **pytesseract** chama o mecanismo Tesseract OCR instalado separadamente no Windows. O OCR roda aproximadamente uma vez por segundo.
- A confiança do Tesseract **não é uma probabilidade calibrada de acerto**. A palavra pode vir de controles da plataforma; mantenha a região restrita ao gráfico.
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

1. Selecione apenas o gráfico/indicador; exclua botões da corretora, janela do AUTO TRADER, banners e menus.
2. Marque **Ativar OCR experimental COMPRA/VENDER** antes de iniciar a visualização.
3. Confira os candidatos e selecione uma etiqueta na tabela. O rótulo e sua caixa no preview devem coincidir com a etiqueta do indicador.
4. Clique **Armar candidato selecionado**. O aplicativo fica pendente e não registra uma entrada ainda.
5. Somente depois de observar que a próxima vela N+1 nasceu, clique **Confirmar abertura da próxima vela**. O resultado é marcado como entrada simulada em memória. Use **Cancelar** para descartar o pendente; a mesma etiqueta não será rearmada naquela sessão.

Testes unitários (não precisam de tela gráfica nem do mecanismo Tesseract):

```powershell
python -m unittest discover -s tests -v
```

## Limitações / próxima etapa

- O OCR não distingue se uma palavra é etiqueta do indicador, texto histórico ou botão da plataforma. A seleção manual do candidato ainda é necessária.
- A confirmação da abertura da próxima vela é manual porque ainda não foi validado um método visual confiável para detectar vela/candle identity, rolagem do gráfico e período configurado.
- O histórico da simulação é apenas em memória; não mede lucro, não verifica aceitação de ordem e não usa dados de mercado.
- Antes de automatizar essa confirmação, será necessário validar capturas sequenciais reais com o ativo e o período gráfico usados. Em qualquer incerteza, a ação segura é não simular/operar.
- Operações financeiras envolvem risco e podem estar sujeitas às regras da plataforma. Execução real continua fora do escopo.
