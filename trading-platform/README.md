# Trading Control Center

Plataforma completa, moderna e configurável para **gerenciamento de banca, registro de operações e acompanhamento de resultados** de Trading / Opções Binárias.

Interface em português, inspirada em dashboards financeiros profissionais, com uma visão de planilha / micro séries baseada no modelo enviado.

---

## Como executar

```bash
cd trading-platform
npm install
npm run dev
```

Abra `http://localhost:5173`. Para gerar a versão de produção:

```bash
npm run build
npm run preview
```

Não é necessário servidor, banco de dados ou conta: **todos os dados ficam no `localStorage` do navegador** e são gravados automaticamente a cada alteração (persistem após atualizar, fechar ou reiniciar a aplicação).

> Para migrar entre navegadores ou dispositivos, use **Histórico & dados → Fazer backup / Restaurar de arquivo**.

### Restaurar um backup

1. Menu lateral → **Histórico & dados** (ou Atalhos → **Backup & segurança**).
2. Em *Backup, restauração e persistência*, clique em **Restaurar de arquivo**.
3. Selecione o `.json` gerado por **Fazer backup** (`backup-trading-AAAA-MM-DD.json`).
4. Confira o modal e clique em **Restaurar e substituir dados atuais**.

A restauração substitui **todos** os dados atuais (operações, estratégias, movimentações, screenshots, metas e personalizações). Faça um backup do estado atual antes de restaurar. Arquivos `.csv`/`.xlsx` são exportações para leitura, **não** servem para restaurar — apenas o `.json`. Os dados ficam no `localStorage` do navegador (chave `tcc:data:v1`): limpar os dados do navegador apaga tudo, e sem backup não há como recuperar.

---

## Módulos

| Módulo | O que entrega |
| --- | --- |
| **Dashboard** | Saldo inicial/atual, resultado do dia e acumulado, rentabilidade, total de operações, WIN/LOSS/DRAW, assertividade, payout médio, valor médio, maiores sequências, melhor/pior dia, meta diária com progresso, limite de perda e quanto ainda pode perder, próxima entrada sugerida e gráficos. Todos os cards podem ser reordenados, ocultados e redimensionados (arrastar no modal "Personalizar cards"). |
| **Banca** | Banca inicial, ajuste auditável do saldo atual, valor base/mínimo/máximo, risco por operação, meta e stops (R$ ou %), limites de operações e de sequências, exposição máxima, reserva de lucro, depósitos, retiradas e histórico de movimentações. |
| **Gerenciamento de entradas** | 7 modalidades independentes (Valor fixo, % da banca, Soros N1, Soros N2, Soros personalizado, Martingale, sequência personalizada), cálculo da próxima entrada com todos os limites aplicados, bloqueios/avisos de risco e simulador de ciclo. |
| **Registro de operações** | Data, horário, ativo, mercado (OTC/Normal), direção (CALL/PUT), estratégia, timeframe, expiração, entrada, payout, resultado, lucro calculado automaticamente (com correção manual opcional), observações, screenshot comprimida e micro série. Editar, excluir, duplicar e colunas/campos configuráveis. |
| **Resultados diários** | Todos os indicadores do dia, horários mais lucrativos, estratégias usadas, sequência de resultados, progresso da meta e calendário mensal interativo com dias positivos/negativos/vazios/meta atingida/stop alcançado. Clique em um dia para ver todas as operações e anotações. |
| **Relatórios & estatísticas** | Equity Curve, resultado por dia/semana/mês, assertividade ao longo do tempo, distribuição WIN/LOSS/DRAW, desempenho por ativo, estratégia, horário, timeframe e payout, comparação entre estratégias e tabelas detalhadas. Filtro por qualquer intervalo de datas e tooltips interativos. |
| **Estratégias** | Cadastro completo (nome, descrição, configuração, ativos, timeframe, expiração, cor, status), estatísticas calculadas do histórico real (total, W/L/D, assertividade, lucro, melhor horário, payout médio) e ranking automático. Ativar, desativar, editar e excluir sem perder o histórico. |
| **Metas & planejamento** | Metas diária/semanal/mensal/de crescimento, objetivo financeiro, limite de perda, operações desejadas, progresso de cada objetivo e planos de crescimento com cenários conservador/realista/agressivo. |
| **Planilha / Micro séries** | Visão em planilha com linhas verdes/vermelhas, blocos de micro séries, `% Micro Série`, `Investimento`, `Retorno`, `Capital Atual`, setas de "Repor Aqui", linha de `Resultados` e `Lucro de X% \| Y%`. Exportação CSV. |
| **Histórico & dados** | Filtros avançados, pesquisa, edição/exclusão, **importação de planilhas Excel/CSV**, exportação CSV e Excel (.xlsx multi-abas), backup/restauração JSON, separação explícita entre dados reais e simulações. |
| **Personalização** | Nome e subtítulo, tema claro/escuro, cores, moeda (BRL/USD/EUR/GBP/ARS/JPY + símbolo livre), localidade, formato de datas, números compactos, cards, colunas, campos do formulário, preferências de gráficos e período padrão dos filtros. |

---

## Importar resultados do Excel

Acesse por qualquer um destes atalhos: botão **Importar do Excel** no topo, item **Importar do Excel** no menu lateral, **Importar Excel** em Registro de operações, **Importar planilha** no estado vazio do Dashboard ou a seção **Importação de planilhas** em Histórico & dados.

1. Clique em **Escolher arquivo** (ou arraste o arquivo). Formatos: `.xlsx`, `.xls`, `.xlsm`, `.csv` (`;` ou `,`), `.tsv`.
2. Confira a **aba** e a **linha do cabeçalho** (detectadas automaticamente).
3. Confira/ajuste o **mapeamento de colunas**. São reconhecidos automaticamente nomes como `Data`, `Horário`, `Ativo`, `Investimento`/`Entrada`, `Payout (%)`, `Resultado`/`W - L`, `Retorno`/`Lucro`, `Estratégia`, `Observações`, `Micro série`.
4. Ajuste as **opções**: payout padrão, data padrão, ordem dia/mês/ano, recalcular lucro, ignorar duplicatas, criar estratégias automaticamente e marcar como SIMULAÇÃO.
5. Analise a **prévia**: total de linhas, quantidade válida, erros, duplicatas e avisos. Nada é gravado nesta etapa.
6. Clique em **Importar N operação(ões)**. Os indicadores são recalculados na hora.

O botão **Baixar modelo .xlsx** gera uma planilha com apenas os cabeçalhos e uma aba de instruções — sem dados fictícios.

Normalizações aceitas: datas `dd/MM/yyyy`, ISO, serial do Excel e datas com horário; valores `R$ 1.234,56`, `1,234.56`, `-R$ 21,00`, `85%`, frações `0,85 → 85%`; resultados `W/WIN/GANHO`, `L/LOSS/PERDA`, `D/DRAW/EMPATE`. Se não houver coluna de resultado, ele é inferido pelo lucro (positivo → WIN, negativo → LOSS, zero → DRAW).

Registros importados recebem o selo **IMPORTADO**, podem ser editados/excluídos normalmente e são identificados na coluna "Tipo de dado" das exportações. Limites operacionais (stop, risco, exposição) continuam valendo para novas operações, mas não bloqueiam a carga de histórico.

---

## Regras de cálculo

- **WIN** → `entrada × payout%` (lucro líquido, como no modelo enviado).
- **LOSS** → `-entrada`; **DRAW** → `0`.
- **Saldo** = `banca inicial + depósitos − retiradas + ajustes + soma dos resultados`.
- **Assertividade** = `WIN / (WIN + LOSS)` (DRAW não conta como decisão).
- Metas e stops em `%` usam o **saldo de abertura do dia**.
- A entrada sugerida é limitada por: valor mínimo/máximo, risco por operação, exposição máxima da banca, stop loss/gain, limite de operações por dia, limites de sequências e saldo disponível.
- Registrar uma operação que viole limites exige **confirmação explícita** no formulário (configurável).

---

## Dados reais × exemplos × simulações

A plataforma **começa vazia**. Nenhum número fictício é exibido como se fosse operação real.

- O botão **"Carregar exemplo demonstrativo"** cria registros com `demo: true`, identificados pelo selo `SIMULAÇÃO`.
- Por padrão, simulações **não entram** em nenhum cálculo. O ícone de laboratório no topo as inclui apenas na visualização.
- O **simulador de ciclo** e as **projeções de crescimento** não gravam nada no histórico.
- Projeções são **estimativas matemáticas, não garantias de resultados futuros**. Trading envolve risco real de perda.

Esta é uma ferramenta de registro e controle: não executa operações, não se conecta a corretoras e não oferece recomendações de investimento.

---

## Tecnologias

React 19 + TypeScript + Vite · Recharts (gráficos interativos) · Lucide (ícones) · SheetJS (exportação Excel, carregado sob demanda) · CSS puro com variáveis para temas e cores personalizáveis.
