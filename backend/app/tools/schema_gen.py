"""Tables -> prisma/schema.prisma + db/init.sql (PostgreSQL or MySQL), type-compatible with each other."""

import re
from dataclasses import dataclass
from typing import Literal

from app.schemas import Column, Table
from app.tools.base import ToolOutput

Provider = Literal["postgres", "mysql"]

CANONICAL_TYPES = ("String", "Int", "BigInt", "Float", "Decimal", "Boolean", "DateTime", "Json", "Uuid")

_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"uuid|guid", "Uuid"),
    (r"bigint|bigserial|int8|long", "BigInt"),
    (r"^(int|integer|serial|smallint|int4|int2|number|num|tinyint)", "Int"),
    (r"decimal|numeric|money|price|currency", "Decimal"),
    (r"float|double|real", "Float"),
    (r"bool|bit", "Boolean"),
    (r"date|time|timestamp", "DateTime"),
    (r"json|object|map|dict", "Json"),
    (r"char|text|string|str|varchar|email|url|enum", "String"),
]


@dataclass(frozen=True)
class Dialect:
    quote: str
    types: dict[str, str]
    auto: dict[str, str]  # column type -> full "TYPE ... PRIMARY KEY ..." for generated keys
    now_default: str
    prisma_provider: str


DIALECTS: dict[Provider, Dialect] = {
    "postgres": Dialect(
        quote='"',
        types={
            "String": "TEXT",
            "Int": "INTEGER",
            "BigInt": "BIGINT",
            "Float": "DOUBLE PRECISION",
            "Decimal": "DECIMAL(65,30)",
            "Boolean": "BOOLEAN",
            "DateTime": "TIMESTAMP(3)",
            "Json": "JSONB",
            "Uuid": "UUID",
        },
        auto={
            "Int": "SERIAL PRIMARY KEY",
            "BigInt": "BIGSERIAL PRIMARY KEY",
            "Uuid": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
        },
        now_default="DEFAULT CURRENT_TIMESTAMP",
        prisma_provider="postgresql",
    ),
    # MySQL can't index TEXT without a prefix length, so strings are VARCHAR(191) (Prisma's default).
    "mysql": Dialect(
        quote="`",
        types={
            "String": "VARCHAR(191)",
            "Int": "INT",
            "BigInt": "BIGINT",
            "Float": "DOUBLE",
            "Decimal": "DECIMAL(65,30)",
            "Boolean": "BOOLEAN",
            "DateTime": "DATETIME(3)",
            "Json": "JSON",
            "Uuid": "CHAR(36)",
        },
        auto={
            "Int": "INT AUTO_INCREMENT PRIMARY KEY",
            "BigInt": "BIGINT AUTO_INCREMENT PRIMARY KEY",
            "Uuid": "CHAR(36) PRIMARY KEY DEFAULT (UUID())",
        },
        now_default="DEFAULT CURRENT_TIMESTAMP(3)",
        prisma_provider="mysql",
    ),
}


def normalize_type(raw: str | None) -> str:
    if not raw:
        return "String"
    for canonical in CANONICAL_TYPES:
        if raw == canonical:
            return canonical
    low = raw.strip().lower()
    for pattern, canonical in _TYPE_PATTERNS:
        if re.search(pattern, low):
            return canonical
    return "String"


def snake(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    if not s:
        s = "unnamed"
    return f"t_{s}" if s[0].isdigit() else s


def pascal(name: str) -> str:
    return "".join(p.capitalize() for p in snake(name).split("_"))


def _pks(table: Table) -> list[Column]:
    return [c for c in table.columns if c.pk]


def _prepare(tables: list[Table]) -> tuple[list[Table], list[str]]:
    """Copy, ensure a PK per table, and resolve/validate FKs."""
    warnings: list[str] = []
    prepared: list[Table] = []
    for t in tables:
        cols = [
            c.model_copy(update={"name": snake(c.name), "type": normalize_type(c.type)}) for c in t.columns
        ]
        table = Table(name=snake(t.name), columns=cols)
        if not _pks(table):
            if any(c.name == "id" for c in table.columns):
                next(c for c in table.columns if c.name == "id").pk = True
            else:
                table.columns.insert(0, Column(name="id", type="Int", pk=True, nullable=False))
        for c in _pks(table):
            c.nullable = False
        prepared.append(table)

    by_name = {t.name: t for t in prepared}
    for table in prepared:
        for col in table.columns:
            if not col.fk:
                continue
            ref_table, _, ref_col = col.fk.replace("(", ".").replace(")", "").partition(".")
            ref = by_name.get(snake(ref_table))
            if ref is None:
                warnings.append(
                    f"{table.name}.{col.name}: referenced table '{ref_table}' not found; FK dropped."
                )
                col.fk = None
                continue
            pks = _pks(ref)
            target = next((c for c in ref.columns if c.name == snake(ref_col or "")), None)
            if target is None or not (target.pk or target.unique):
                if len(pks) != 1:
                    warnings.append(f"{table.name}.{col.name}: no single key on '{ref.name}'; FK dropped.")
                    col.fk = None
                    continue
                target = pks[0]
            col.fk = f"{ref.name}.{target.name}"
            col.type = target.type
    return prepared, warnings


def _is_auto(table: Table, col: Column) -> bool:
    return col.pk and not col.fk and len(_pks(table)) == 1 and col.type in ("Int", "BigInt", "Uuid")


def _render_sql(tables: list[Table], d: Dialect) -> str:
    def q(name: str) -> str:
        return f"{d.quote}{name}{d.quote}"

    lines = ["-- Generated by Diagram2Repo. Runs automatically on first `docker compose up`.", ""]
    fks: list[str] = []
    for t in tables:
        single_pk = len(_pks(t)) == 1
        defs: list[str] = []
        for c in t.columns:
            if _is_auto(t, c):
                defs.append(f"{q(c.name)} {d.auto[c.type]}")
                continue
            parts = [q(c.name), d.types[c.type]]
            if c.pk and single_pk:
                parts.append("PRIMARY KEY")
            elif not c.nullable:
                parts.append("NOT NULL")
            if c.unique and not c.pk:
                parts.append("UNIQUE")
            if c.type == "DateTime" and c.name in ("created_at", "createdat"):
                parts.append(d.now_default)
            defs.append(" ".join(parts))
            if c.fk:
                ref_t, ref_c = c.fk.split(".")
                fks.append(
                    f"ALTER TABLE {q(t.name)} ADD CONSTRAINT {q(f'{t.name}_{c.name}_fkey')} "
                    f"FOREIGN KEY ({q(c.name)}) REFERENCES {q(ref_t)} ({q(ref_c)});"
                )
        if not single_pk:
            defs.append("PRIMARY KEY (" + ", ".join(q(c.name) for c in _pks(t)) + ")")
        lines.append(f"CREATE TABLE IF NOT EXISTS {q(t.name)} (")
        lines.append(",\n".join(f"  {d}" for d in defs))
        lines.append(");")
        lines.append("")
    if fks:
        lines.append("-- Foreign keys (added last so table order does not matter)")
        lines.extend(fks)
        lines.append("")
    return "\n".join(lines)


def _prisma_type(c: Column, provider: Provider) -> tuple[str, list[str]]:
    if c.type == "Uuid":
        return "String", ["@db.Uuid" if provider == "postgres" else "@db.Char(36)"]
    return c.type, []


def _render_prisma(tables: list[Table], provider: Provider) -> str:
    models = {t.name: pascal(t.name) for t in tables}
    fields: dict[str, list[str]] = {t.name: [] for t in tables}
    taken: dict[str, set[str]] = {t.name: {c.name for c in t.columns} for t in tables}
    back_refs: dict[str, list[str]] = {t.name: [] for t in tables}

    def unique_name(table: str, base: str) -> str:
        name, i = base, 2
        while name in taken[table]:
            name, i = f"{base}{i}", i + 1
        taken[table].add(name)
        return name

    for t in tables:
        single_pk = len(_pks(t)) == 1
        for c in t.columns:
            base, attrs = _prisma_type(c, provider)
            optional = "?" if c.nullable and not c.pk else ""
            mods: list[str] = []
            if c.pk and single_pk:
                mods.append("@id")
                if _is_auto(t, c):
                    if c.type != "Uuid":
                        mods.append("@default(autoincrement())")
                    elif provider == "postgres":
                        mods.append('@default(dbgenerated("gen_random_uuid()"))')
                    else:
                        mods.append("@default(uuid())")
            if c.unique and not c.pk:
                mods.append("@unique")
            if c.type == "DateTime" and c.name in ("created_at", "createdat"):
                mods.append("@default(now())")
            fields[t.name].append(f"  {c.name} {base}{optional} {' '.join(mods + attrs)}".rstrip())

        for c in t.columns:
            if not c.fk:
                continue
            ref_t, ref_c = c.fk.split(".")
            rel = f"{models[t.name]}_{c.name}"
            fname = unique_name(t.name, c.name[:-3] if c.name.endswith("_id") else f"{ref_t}_ref")
            optional = "?" if c.nullable else ""
            relation = f'@relation("{rel}", fields: [{c.name}], references: [{ref_c}])'
            fields[t.name].append(f"  {fname} {models[ref_t]}{optional} {relation}")
            many = "?" if c.unique or (c.pk and single_pk) else "[]"
            back = unique_name(ref_t, t.name if many == "[]" else snake(models[t.name]))
            back_refs[ref_t].append(f'  {back} {models[t.name]}{many} @relation("{rel}")')

    out = [
        "// Generated by Diagram2Repo",
        "generator client {",
        '  provider = "prisma-client-js"',
        "}",
        "",
        "datasource db {",
        f'  provider = "{DIALECTS[provider].prisma_provider}"',
        '  url      = env("DATABASE_URL")',
        "}",
        "",
    ]
    for t in tables:
        out.append(f"model {models[t.name]} {{")
        out.extend(fields[t.name] + back_refs[t.name])
        if len(_pks(t)) > 1:
            out.append("")
            out.append("  @@id([" + ", ".join(c.name for c in _pks(t)) + "])")
        if models[t.name] != t.name:
            out.append(f'  @@map("{t.name}")')
        out.append("}")
        out.append("")
    return "\n".join(out)


def generate_db_schema(tables: list[Table], provider: Provider = "postgres") -> ToolOutput:
    out = ToolOutput()
    if not tables:
        out.warnings.append("No tables were extracted; skipping schema generation.")
        return out
    prepared, out.warnings = _prepare(tables)
    out.files["prisma/schema.prisma"] = _render_prisma(prepared, provider)
    out.files["db/init.sql"] = _render_sql(prepared, DIALECTS[provider])
    out.data = {
        "provider": provider,
        "tables": [t.name for t in prepared],
        "foreign_keys": [f"{t.name}.{c.name} -> {c.fk}" for t in prepared for c in t.columns if c.fk],
    }
    return out
