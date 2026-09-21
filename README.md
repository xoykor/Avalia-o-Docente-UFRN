# Avaliação Docente UFRN

Interface web estática para consulta de avaliações de docentes da **Universidade Federal do Rio Grande do Norte (UFRN)** a partir de um banco SQLite distribuído junto ao projeto.

## Como funciona

A aplicação carrega o banco `database.sqlite` diretamente no navegador usando **sql.js/WebAssembly**. Os dados são consultados localmente pelo frontend, sem necessidade de servidor de aplicação ou API.

Os resultados são apresentados por docente e podem incluir filtros, estatísticas e visualizações gráficas geradas no navegador.

## Tecnologias

- HTML, CSS e JavaScript;
- SQLite;
- sql.js / WebAssembly;
- Chart.js.

## Estrutura

```text
.
├── index.html
├── database.sqlite
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

## Privacidade e arquitetura

A consulta é feita no próprio navegador. O repositório não contém um backend de autenticação nem um serviço remoto de consulta. Isso simplifica a implantação, mas também significa que o banco distribuído no repositório é acessível a qualquer pessoa que tenha acesso ao site ou ao código.

## Limitações

- a qualidade das visualizações depende da qualidade e cobertura do banco incluído;
- o projeto não substitui sistemas institucionais da UFRN;
- os dados devem ser interpretados dentro do contexto e metodologia da fonte que os originou.

## Licença

GNU General Public License v3.0. Consulte [LICENSE](LICENSE).
