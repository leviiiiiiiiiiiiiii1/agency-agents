# AUTO TRADER IQ — Etapa 2: OCR experimental de BUY/SELL

Protótipo para selecionar e visualizar uma região da tela e, opcionalmente, procurar os textos BUY/SELL com OCR. **O resultado é apenas um candidato visual para revisão humana**: não valida o sinal, não associa o texto a uma vela, não clica, não envia ordens e não interage com a corretora. O OCR começa desligado.

## Arquitetura e decisões técnicas

- **Python 3.12+** e `tkinter` para a interface local.
- **MSS** captura apenas a região selecionada; **Pillow** prepara e anota o preview.
- **pytesseract** chama o mecanismo Tesseract OCR instalado separadamente no Windows. O mecanismo roda uma vez por segundo, não em todos os quadros.
- São aceitas somente palavras exatas BUY e SELL após normalização simples e o limite de confiança configurado. A confiança do Tesseract **não é uma probabilidade calibrada de acerto**.
- O preview desenha caixas sobre o texto detectado. Sem caixa não significa que não existe sinal: pode haver falha de OCR, baixa resolução, oclusão ou contraste insuficiente.
- Nenhum módulo de automação de mouse/teclado ou envio de ordens existe neste projeto.

## Instalação no Windows

1. Instale Python 3.12 ou superior e confirme `python -m tkinter`.
2. Instale o **Tesseract OCR para Windows** separadamente. O pacote Python `pytesseract` é apenas um adaptador e não instala o executável OCR. Anote o caminho para `tesseract.exe`; o padrão frequente é `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. Abra PowerShell dentro da pasta `auto_trader_iq` do projeto (a que contém `requirements.txt`) e instale as dependências:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
```

Se o ambiente virtual já estiver criado e ativo, não crie outro; basta executar o `pip install` acima nessa pasta.

Se o executável Tesseract não estiver no PATH, configure-o para a sessão atual do PowerShell antes de iniciar:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Executar e testar

Estando na pasta `auto_trader_iq` do projeto:

```powershell
python -m auto_trader_iq.app
```

1. Escolha o monitor e selecione apenas a área do **gráfico/indicador**. Evite incluir os botões de compra/venda da corretora ou outras áreas com palavras BUY/SELL.
2. Para apenas visualizar a tela, deixe **Ativar OCR experimental BUY/SELL** desmarcado e inicie a visualização.
3. Para testar OCR, marque a opção, configure a confiança mínima e inicie. Se o Tesseract não for encontrado, a mensagem de erro informa o que configurar.
4. Compare as caixas e palavras mostradas com o gráfico real. Use **Salvar captura atual…** para guardar uma imagem sem anotação em `%LOCALAPPDATA%\AutoTraderIQ\screenshots\`.
5. A janela inicia parada e o OCR desligado. Parar a visualização interrompe o ciclo.

Testes unitários (não precisam de uma janela gráfica nem do executável Tesseract):

```powershell
python -m unittest discover -s tests -v
```

## Limitações importantes / próximos passos

- O OCR não sabe se o texto foi desenhado pelo indicador ou pertence a outro elemento visível; mantenha a região restrita ao gráfico.
- Ainda não há associação de etiqueta à vela, confirmação de fechamento, deduplicação por identidade da vela, registro persistente ou gerenciamento de risco.
- As coordenadas e a detecção precisam ser verificadas com imagens reais de BUY e SELL, em diferentes temas/zoom e em modo de replay ou simulação. Dúvida significa ignorar o candidato, nunca operar.
- Não se pode inferir o fechamento efetivo da vela apenas pelo relógio local. Isso exige uma fonte temporal confiável da plataforma; se não puder ser confirmada, o processo deve aguardar.
- Automação de operações financeiras apresenta risco e pode estar sujeita às regras da plataforma. Esta aplicação continua sendo apenas uma ferramenta de observação; não executa operações reais.
