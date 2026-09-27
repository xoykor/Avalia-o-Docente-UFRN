# Avaliação Docente UFRN

Interface web estática para consulta de avaliações de docentes da **Universidade Federal do Rio Grande do Norte (UFRN)** a partir de um banco SQLite distribuído junto ao projeto.

## Como funciona

A aplicação carrega o banco `database.sqlite` diretamente no navegador usando **sql.js/WebAssembly**. Os dados são consultados localmente pelo frontend, sem necessidade de servidor de aplicação ou API.

Os resultados são apresentados por docente e podem incluir filtros, estatísticas e visualizações gráficas geradas no navegador.

Além das avaliações discentes, o projeto cruza as turmas avaliadas com os conjuntos oficiais **Matrículas em Componentes**, **Turmas** e **Componentes Curriculares** para calcular taxa histórica de aprovação por disciplina e docente.

## Tecnologias

- HTML, CSS e JavaScript;
- SQLite;
- sql.js / WebAssembly;
- Chart.js;
- GitHub Actions para atualizar os dados derivados de aprovação.

## Estrutura

```text
.
├── index.html
├── database.sqlite
├── scripts/
│   └── enrich_approval.py
├── .github/workflows/
│   └── update-approval.yml
├── lib/
│   ├── sql-wasm.min.js
│   └── ...
└── LICENSE
```

## Executar localmente

Como o navegador precisa carregar o banco e os arquivos WebAssembly por HTTP, evite abrir o `index.html` diretamente com `file://`.

Use um servidor estático, por exemplo:

```sh
python -m http.server 8000
```

Depois acesse:

```text
http://127.0.0.1:8000
```

## Taxa de aprovação

A comparação por aprovação é feita **por disciplina**, evitando comparar diretamente componentes com perfis de dificuldade diferentes.

A taxa exibida é:

`aprovados / (aprovados + reprovados)`

Entram no denominador apenas situações finais cujo texto começa por `APROVADO` ou `REPROVADO`. Trancamentos, cancelamentos e situações ainda sem resultado final são excluídos. A interface também permite exigir uma amostra mínima de resultados antes de incluir um docente no comparativo.

Quando uma turma possui mais de um docente associado nos dados de avaliação, o resultado acadêmico da turma aparece associado a cada um deles; portanto, a taxa deve ser lida como histórico das turmas em que o docente atuou, não como atribuição causal individual.

O script `scripts/enrich_approval.py` descobre os CSVs publicados no CKAN da UFRN, agrega os resultados e grava a tabela `aprovacao_turmas` no SQLite. O workflow `update-approval.yml` executa essa atualização periodicamente e também pode ser disparado manualmente.

## Privacidade e arquitetura

A consulta é feita no próprio navegador. O repositório não contém um backend de autenticação nem um serviço remoto de consulta. Isso simplifica a implantação, mas também significa que o banco distribuído no repositório é acessível a qualquer pessoa que tenha acesso ao site ou ao código.

## Limitações

- a qualidade das visualizações depende da qualidade e cobertura do banco incluído;
- o projeto não substitui sistemas institucionais da UFRN;
- os dados devem ser interpretados dentro do contexto e metodologia da fonte que os originou.

## Licença

GNU General Public License v3.0. Consulte [LICENSE](LICENSE).
