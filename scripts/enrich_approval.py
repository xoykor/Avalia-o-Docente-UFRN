#!/usr/bin/env python3
"""Enriquece database.sqlite com taxas de aprovação por docente/turma/componente.

Fontes oficiais: Dados Abertos da UFRN (CKAN):
- Avaliação de Docência já presente em database.sqlite
- Matrículas em Componentes
- Turmas
- Componentes Curriculares

A taxa considera apenas resultados finais:
  aprovado = situações que começam por "APROVADO"
  reprovado = situações que começam por "REPROVADO"
Cancelamentos, trancamentos e matrículas sem resultado final ficam fora do denominador.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import sqlite3
import sys
import unicodedata
import urllib.request
from html import unescape
from urllib.parse import urljoin
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CKAN = "https://dados.ufrn.br/api/3/action/package_show?id={}"
USER_AGENT = "Avalia-o-Docente-UFRN/1.0 (+https://github.com/xoykor/Avalia-o-Docente-UFRN)"


def fetch_bytes(url: str, *, timeout: int = 120, attempts: int = 5) -> bytes:
    """Baixa uma URL com retry exponencial.

    O portal da UFRN ocasionalmente aceita a conexão mas demora a responder.
    Ler o corpo inteiro dentro da tentativa também permite repetir downloads
    interrompidos no meio, em vez de deixar o pipeline morrer.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Connection": "close",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = min(20, 2 ** attempt)
            print(
                f"[rede] tentativa {attempt}/{attempts} falhou para {url}: {exc}; "
                f"nova tentativa em {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError(f"Falha ao baixar {url} após {attempts} tentativas") from last_error


def request_json(url: str) -> dict:
    return json.loads(fetch_bytes(url, timeout=45, attempts=5).decode("utf-8-sig"))


def resources_from_dataset_page(package: str) -> list[dict]:
    """Fallback quando o endpoint CKAN /api/3/action fica indisponível."""
    page_url = f"https://dados.ufrn.br/dataset/{package}"
    html = unescape(fetch_bytes(page_url, timeout=60, attempts=5).decode("utf-8", "replace"))

    # O CKAN inclui os links de download dos recursos no HTML da página.
    candidates = re.findall(
        r"""(?:href|data-url)=["']([^"']+?\.csv(?:\?[^"']*)?)["']""",
        html,
        flags=re.IGNORECASE,
    )
    # Alguns temas também colocam a URL absoluta como texto/atributo JSON.
    candidates += re.findall(
        r"""(https?://dados\.ufrn\.br/dataset/[^"'<>\s]+?\.csv(?:\?[^"'<>\s]*)?)""",
        html,
        flags=re.IGNORECASE,
    )

    resources = []
    seen = set()
    for candidate in candidates:
        url = urljoin(page_url, candidate)
        if url in seen:
            continue
        seen.add(url)
        resources.append(
            {
                "name": url.split("?")[0].rsplit("/", 1)[-1],
                "url": url,
                "format": "CSV",
            }
        )
    if not resources:
        raise RuntimeError(f"Nenhum CSV encontrado na página pública de {package}")
    print(f"[rede] usando fallback HTML para {package}: {len(resources)} CSV(s).")
    return resources


def package_resources(package: str) -> list[dict]:
    try:
        payload = request_json(CKAN.format(package))
        if not payload.get("success"):
            raise RuntimeError(f"CKAN não retornou sucesso para {package}")
        return payload["result"]["resources"]
    except Exception as exc:
        print(
            f"[rede] API CKAN indisponível para {package}: {exc}. "
            "Tentando a página pública do conjunto.",
            file=sys.stderr,
        )
        return resources_from_dataset_page(package)


def norm(value: str | None) -> str:
    text = unicodedata.normalize("NFD", value or "")
    return "".join(c for c in text if unicodedata.category(c) != "Mn").upper().strip()


def as_int(value: str | int | float | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value).replace(",", ".")))
        except (TypeError, ValueError):
            return None


def first_present(row: dict, names: tuple[str, ...]) -> str | None:
    lowered = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def rows_from_csv(url: str):
    raw = fetch_bytes(url, timeout=180, attempts=5)
    text = io.TextIOWrapper(
        io.BytesIO(raw),
        encoding="utf-8-sig",
        errors="replace",
        newline="",
    )
    first = text.readline()
    if not first:
        return
    delimiter = ";" if first.count(";") >= first.count(",") else ","
    header = next(csv.reader([first], delimiter=delimiter))
    header = [h.strip() for h in header]
    reader = csv.DictReader(text, fieldnames=header, delimiter=delimiter)
    yield from reader


def semester_from_resource(resource: dict) -> tuple[int, int] | None:
    hay = f"{resource.get('name', '')} {resource.get('url', '')}"
    match = re.search(r"(20\d{2})[._-]?([1256])(?:\D|$)", hay)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def csv_resources_for_semesters(package: str, wanted: set[tuple[int, int]]) -> list[tuple[tuple[int, int], dict]]:
    found = []
    for resource in package_resources(package):
        fmt = str(resource.get("format") or "").lower()
        url = resource.get("url")
        if not url or ("csv" not in fmt and not str(url).lower().endswith(".csv")):
            continue
        sem = semester_from_resource(resource)
        if sem in wanted:
            found.append((sem, resource))
    return sorted(found, key=lambda item: item[0])


def load_evaluation_links(conn: sqlite3.Connection):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(registros)")}
    required = {"id_docente", "id_turma", "ano", "periodo"}
    missing = required - cols
    if missing:
        raise RuntimeError(f"A tabela registros não contém: {', '.join(sorted(missing))}")

    by_turma: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    semesters: set[tuple[int, int]] = set()
    for id_docente, id_turma, ano, periodo in conn.execute(
        "SELECT id_docente,id_turma,ano,periodo FROM registros WHERE id_turma IS NOT NULL"
    ):
        turma = as_int(id_turma)
        docente = as_int(id_docente)
        ano_i = as_int(ano)
        periodo_i = as_int(periodo)
        if None in (turma, docente, ano_i, periodo_i):
            continue
        by_turma[turma].append((docente, ano_i, periodo_i))
        semesters.add((ano_i, periodo_i))
    return by_turma, semesters


def collect_results(wanted_turmas: set[int], semesters: set[tuple[int, int]]):
    counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    resources = csv_resources_for_semesters("matriculas-componentes", semesters)
    if not resources:
        raise RuntimeError("Nenhum CSV de Matrículas em Componentes foi localizado no CKAN.")

    for sem, resource in resources:
        print(f"[matrículas] {sem[0]}.{sem[1]} — {resource.get('name')}")
        # O conjunto pode conter mais de uma linha por discente (ex.: unidades/notas).
        # Contamos cada discente no máximo uma vez por turma, apenas quando já existe
        # uma situação final de aprovação ou reprovação.
        seen_enrollments: set[tuple[int, str]] = set()
        fallback_row = 0
        for row in rows_from_csv(resource["url"]):
            turma = as_int(first_present(row, ("id_turma",)))
            if turma not in wanted_turmas:
                continue
            status = norm(first_present(row, ("descricao", "situacao", "situação", "status")))
            if not (status.startswith("APROVADO") or status.startswith("REPROVADO")):
                continue

            discente = first_present(
                row,
                ("discente", "id_discente", "matricula", "matrícula", "registro_discente"),
            )
            if discente is not None and str(discente).strip():
                enrollment_key = (turma, str(discente).strip())
            else:
                # Fallback conservador para formatos antigos que não exponham
                # identificador do discente.
                fallback_row += 1
                enrollment_key = (turma, f"__row_{fallback_row}")

            if enrollment_key in seen_enrollments:
                continue
            seen_enrollments.add(enrollment_key)

            if status.startswith("APROVADO"):
                counts[turma][0] += 1
            else:
                counts[turma][1] += 1
    return counts


def collect_turma_components(wanted_turmas: set[int], semesters: set[tuple[int, int]]):
    turma_component: dict[int, int] = {}
    resources = csv_resources_for_semesters("turmas", semesters)
    if not resources:
        raise RuntimeError("Nenhum CSV de Turmas foi localizado no CKAN.")

    for sem, resource in resources:
        print(f"[turmas] {sem[0]}.{sem[1]} — {resource.get('name')}")
        for row in rows_from_csv(resource["url"]):
            turma = as_int(first_present(row, ("id_turma",)))
            if turma not in wanted_turmas:
                continue
            component = as_int(first_present(row, ("id_componente_curricular", "id_componente")))
            if component is not None:
                turma_component[turma] = component
    return turma_component


def collect_component_names(wanted_components: set[int]):
    components: dict[int, tuple[str | None, str | None]] = {}
    for resource in package_resources("componentes-curriculares"):
        fmt = str(resource.get("format") or "").lower()
        url = resource.get("url")
        if not url or ("csv" not in fmt and not str(url).lower().endswith(".csv")):
            continue
        print(f"[componentes] {resource.get('name')}")
        for row in rows_from_csv(url):
            cid = as_int(first_present(row, ("id_componente", "id_componente_curricular")))
            if cid not in wanted_components:
                continue
            codigo = first_present(row, ("codigo", "codigo_componente", "código"))
            nome = first_present(row, ("nome", "nome_componente"))
            components[cid] = (
                str(codigo).strip() if codigo else None,
                str(nome).strip() if nome else None,
            )
        if wanted_components and wanted_components.issubset(components):
            break
    return components


def write_approval_table(
    conn: sqlite3.Connection,
    eval_by_turma: dict[int, list[tuple[int, int, int]]],
    counts: dict[int, list[int]],
    turma_component: dict[int, int],
    components: dict[int, tuple[str | None, str | None]],
):
    conn.executescript(
        """
        DROP TABLE IF EXISTS aprovacao_turmas;
        CREATE TABLE aprovacao_turmas (
            id_docente INTEGER NOT NULL,
            id_turma INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            periodo INTEGER NOT NULL,
            id_componente_curricular INTEGER,
            codigo_componente TEXT,
            nome_componente TEXT,
            aprovados INTEGER NOT NULL,
            reprovados INTEGER NOT NULL,
            total_finalizados INTEGER NOT NULL,
            taxa_aprovacao REAL NOT NULL,
            PRIMARY KEY (id_docente, id_turma)
        );
        CREATE INDEX idx_aprovacao_docente ON aprovacao_turmas(id_docente);
        CREATE INDEX idx_aprovacao_componente ON aprovacao_turmas(id_componente_curricular);
        CREATE INDEX idx_aprovacao_periodo ON aprovacao_turmas(ano, periodo);

        CREATE TABLE IF NOT EXISTS metadados (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );
        """
    )

    rows = []
    for turma, links in eval_by_turma.items():
        aprovados, reprovados = counts.get(turma, (0, 0))
        total = aprovados + reprovados
        if total == 0:
            continue
        cid = turma_component.get(turma)
        codigo, nome = components.get(cid, (None, None))
        taxa = 100.0 * aprovados / total
        for docente, ano, periodo in links:
            rows.append(
                (docente, turma, ano, periodo, cid, codigo, nome, aprovados, reprovados, total, taxa)
            )

    conn.executemany(
        """
        INSERT OR REPLACE INTO aprovacao_turmas
        (id_docente,id_turma,ano,periodo,id_componente_curricular,codigo_componente,
         nome_componente,aprovados,reprovados,total_finalizados,taxa_aprovacao)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadados(chave,valor) VALUES(?,?)",
        ("aprovacao_atualizada_em", datetime.now(timezone.utc).isoformat()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadados(chave,valor) VALUES(?,?)",
        (
            "aprovacao_metodologia",
            "Aprovados / (Aprovados + Reprovados); cancelamentos, trancamentos e situações sem resultado final excluídos.",
        ),
    )
    conn.commit()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="database.sqlite", help="Caminho do banco SQLite")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Banco não encontrado: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    try:
        eval_by_turma, semesters = load_evaluation_links(conn)
        wanted_turmas = set(eval_by_turma)
        print(f"{len(wanted_turmas):,} turmas avaliadas em {len(semesters)} períodos.")

        counts = collect_results(wanted_turmas, semesters)
        turma_component = collect_turma_components(wanted_turmas, semesters)
        wanted_components = {c for c in turma_component.values() if c is not None}
        components = collect_component_names(wanted_components)

        inserted = write_approval_table(
            conn, eval_by_turma, counts, turma_component, components
        )
        print(
            f"Concluído: {inserted:,} associações docente/turma com resultado final; "
            f"{len(components):,} componentes identificados."
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
