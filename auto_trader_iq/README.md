# AUTO TRADER IQ — Etapa 1: captura da tela

Primeiro módulo funcional para selecionar manualmente e visualizar continuamente uma região de tela. **Esta entrega é somente de captura**: não lê BUY/SELL, não identifica velas, não clica, não envia ordens e não interage com a corretora.

## Arquitetura e decisões técnicas

- **Python 3.12+** e `tkinter` para uma interface local simples (já distribuído com a instalação oficial do Python para Windows).
- **MSS** para captura de regiões/monitores com baixa sobrecarga e sem capturar desnecessariamente toda a tela em cada atualização.
- **Pillow** para conversão, preview redimensionado e gravação opcional de snapshots.
- **Sem OpenCV, Tesseract, PyAutoGUI ou NumPy nesta etapa**: ainda não há processamento de sinais e não se deve incluir automação de entrada real antes de validar captura e reconhecimento. As coordenadas são mantidas em pixels absolutos, incluindo monitores posicionados à esquerda do principal.
- A indicação de “sem mudança visual” é apenas um **sinal heurístico**. Um gráfico parado pode ser legítimo; a captura visual, por si só, não identifica com segurança carregamento, perda de conexão ou congelamento da plataforma.

## Instalação no Windows

1. Instale Python 3.12 ou superior pelo site oficial e marque **Add python.exe to PATH**. Confirme que `tkinter` está disponível com `python -m tkinter`.
2. Abra PowerShell nesta pasta (`auto_trader_iq`) e execute:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Se a política do PowerShell impedir ativação do ambiente, use diretamente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Executar

Com o ambiente virtual ativado e estando dentro de `auto_trader_iq`:

```powershell
python -m auto_trader_iq.app
```

1. Escolha o monitor onde está o gráfico.
2. Clique **Selecionar com o mouse…** e arraste para delimitar a área do gráfico; pressione `Esc` para cancelar.
3. Alternativamente, informe X, Y, largura e altura em pixels e aplique.
4. Inicie a visualização. A janela mostra aproximadamente dois quadros por segundo; “Parar visualização” encerra o ciclo.
5. **Salvar captura atual…** grava o último quadro em PNG para inspeção.

A configuração e os snapshots ficam fora do repositório: `%LOCALAPPDATA%\AutoTraderIQ\` no Windows. A janela inicia sempre com a captura parada. A seleção precisa ser refeita se resolução, escala de DPI ou organização dos monitores mudar.

## Testes

Na pasta `auto_trader_iq`:

```powershell
python -m unittest discover -s tests -v
```

Os testes cobrem validação/conversão de coordenadas sem depender de uma sessão gráfica.

## Limitações e próximas etapas

- Esta etapa não tem detector de BUY/SELL, identidade da vela, validação de fechamento ou banco de operações.
- OCR em etiquetas pequenas e a associação de um marcador à vela correta podem falhar com zoom, tema, escala, sobreposição e atualização da plataforma. Antes de qualquer operação, será necessário testar em modo de replay/simulação com capturas rotuladas e exigir confirmação em mais de um quadro; dúvida deve significar **não operar**.
- O fechamento de vela não deve ser inferido apenas pelo relógio do computador. Sem um sinal confiável da plataforma, o sistema deverá aguardar ou solicitar confirmação manual.
- A execução real em uma corretora envolve risco financeiro, pode contrariar regras/termos da plataforma e um clique não comprova aceitação da ordem. Não faz parte desta etapa; nenhum módulo de clique está incluído.
