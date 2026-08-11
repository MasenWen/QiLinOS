"""Local workplace knowledge tags for Observation candidate generation."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .preference_matching import CanonicalTag


_LATIN_TOKEN = re.compile(r"[a-z0-9]+(?:[.+#_-][a-z0-9]+)*", re.I)
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in value if character.isalnum())


def _search_terms(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    terms = list(_LATIN_TOKEN.findall(normalized))
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            terms.append(run)
            continue
        terms.extend(run[index : index + 2] for index in range(len(run) - 1))
        if len(run) <= 8:
            terms.append(run)
    return tuple(dict.fromkeys(term for term in terms if term))


def _fts_query(value: str) -> str:
    return " OR ".join(
        '"' + term.replace('"', '""') + '"'
        for term in _search_terms(value)
    )


@dataclass(frozen=True)
class KnowledgeTagCandidate:
    tag_id: str
    name: str
    groups: tuple[str, ...]
    pack_id: str
    score: float
    exact_alias: bool
    matched_alias: str


class WorkplaceTagKnowledgeBase:
    """Read-mostly SQLite tag index with exact aliases and FTS5 BM25."""

    schema_version = "workplace.tags.v1"

    def __init__(self, database: str | Path):
        self.database = Path(database)
        if not self.database.is_file():
            raise FileNotFoundError(self.database)
        self._local = threading.local()
        self.tags, self.pack_by_id = self._load_tags()
        self.by_id = {tag.tag_id: tag for tag in self.tags}

    @classmethod
    def build(
        cls,
        database: str | Path,
        tags: Sequence[CanonicalTag],
        *,
        pack_by_tag: dict[str, str] | None = None,
        source_by_tag: dict[str, str] | None = None,
    ) -> "WorkplaceTagKnowledgeBase":
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE tags (
                    tag_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    groups_json TEXT NOT NULL,
                    aliases_json TEXT NOT NULL,
                    prototypes_json TEXT NOT NULL,
                    pack_id TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE TABLE aliases (
                    tag_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    PRIMARY KEY (tag_id, alias)
                );
                CREATE INDEX aliases_normalized_idx ON aliases(normalized);
                CREATE VIRTUAL TABLE alias_fts USING fts5(
                    tag_id UNINDEXED,
                    alias UNINDEXED,
                    search_text,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", cls.schema_version),
            )
            packs = pack_by_tag or {}
            sources = source_by_tag or {}
            for tag in merge_canonical_tags((), tags):
                pack_id = packs.get(tag.tag_id, "workplace-core")
                source = sources.get(tag.tag_id, "bootstrap")
                connection.execute(
                    """
                    INSERT INTO tags(
                        tag_id, name, groups_json, aliases_json,
                        prototypes_json, pack_id, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tag.tag_id,
                        tag.name,
                        json.dumps(tag.groups, ensure_ascii=False),
                        json.dumps(tag.aliases, ensure_ascii=False),
                        json.dumps(tag.prototypes, ensure_ascii=False),
                        pack_id,
                        source,
                    ),
                )
                aliases = tuple(dict.fromkeys((tag.name, *tag.aliases)))
                context = " ".join((*aliases, *tag.prototypes))
                context_terms = " ".join(_search_terms(context))
                for alias in aliases:
                    if not alias.strip():
                        continue
                    connection.execute(
                        "INSERT INTO aliases(tag_id, alias, normalized) VALUES (?, ?, ?)",
                        (tag.tag_id, alias, _normalized(alias)),
                    )
                    search_text = " ".join(
                        dict.fromkeys((*_search_terms(alias), *context_terms.split()))
                    )
                    connection.execute(
                        "INSERT INTO alias_fts(tag_id, alias, search_text) VALUES (?, ?, ?)",
                        (tag.tag_id, alias, search_text),
                    )
            connection.commit()
        finally:
            connection.close()
        return cls(path)

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            uri = f"file:{self.database.resolve().as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            self._local.connection = connection
        return connection

    def _load_tags(
        self,
    ) -> tuple[tuple[CanonicalTag, ...], dict[str, str]]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT * FROM tags ORDER BY tag_id"
            ).fetchall()
        finally:
            connection.close()
        tags = tuple(
            CanonicalTag(
                tag_id=row["tag_id"],
                name=row["name"],
                groups=tuple(json.loads(row["groups_json"])),
                aliases=tuple(json.loads(row["aliases_json"])),
                prototypes=tuple(json.loads(row["prototypes_json"])),
            )
            for row in rows
        )
        return tags, {row["tag_id"]: row["pack_id"] for row in rows}

    def query(
        self,
        text: str,
        *,
        groups: Iterable[str] = ("condition", "object"),
        top_k_per_group: int = 12,
        candidate_limit: int = 160,
    ) -> tuple[KnowledgeTagCandidate, ...]:
        if top_k_per_group < 1:
            raise ValueError("top_k_per_group_must_be_positive")
        query = _fts_query(text)
        if not query:
            return ()
        rows = self._connection().execute(
            """
            SELECT tag_id, alias, bm25(alias_fts) AS rank
            FROM alias_fts
            WHERE alias_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, candidate_limit),
        ).fetchall()
        normalized_text = _normalized(text)
        selected_groups = set(groups)
        best: dict[str, tuple[float, bool, str]] = {}
        for position, row in enumerate(rows):
            tag = self.by_id.get(row["tag_id"])
            if tag is None or not selected_groups.intersection(tag.groups):
                continue
            alias = row["alias"]
            alias_normalized = _normalized(alias)
            exact = bool(
                alias_normalized
                and alias_normalized in normalized_text
                and len(alias_normalized) >= 2
            )
            lexical = 1.0 / (1.0 + 0.035 * position)
            score = lexical + (1.25 if exact else 0.0)
            previous = best.get(tag.tag_id)
            if previous is None or score > previous[0]:
                best[tag.tag_id] = (score, exact, alias)

        candidates = []
        for tag_id, (score, exact, alias) in best.items():
            tag = self.by_id[tag_id]
            candidates.append(
                KnowledgeTagCandidate(
                    tag_id=tag_id,
                    name=tag.name,
                    groups=tag.groups,
                    pack_id=self.pack_by_id[tag_id],
                    score=score,
                    exact_alias=exact,
                    matched_alias=alias,
                )
            )

        retained: dict[str, KnowledgeTagCandidate] = {}
        ranked = sorted(
            candidates,
            key=lambda item: (-item.exact_alias, -item.score, item.tag_id),
        )
        for group in selected_groups:
            group_values = [item for item in ranked if group in item.groups]
            for item in group_values[:top_k_per_group]:
                retained[item.tag_id] = item
        return tuple(
            sorted(
                retained.values(),
                key=lambda item: (-item.exact_alias, -item.score, item.tag_id),
            )
        )

    def statistics(self) -> dict[str, int | str]:
        connection = self._connection()
        return {
            "schema_version": self.schema_version,
            "tag_count": connection.execute(
                "SELECT COUNT(*) FROM tags"
            ).fetchone()[0],
            "alias_count": connection.execute(
                "SELECT COUNT(*) FROM aliases"
            ).fetchone()[0],
            "pack_count": connection.execute(
                "SELECT COUNT(DISTINCT pack_id) FROM tags"
            ).fetchone()[0],
            "database_bytes": self.database.stat().st_size,
        }


def merge_canonical_tags(
    base: Sequence[CanonicalTag],
    extra: Sequence[CanonicalTag],
) -> tuple[CanonicalTag, ...]:
    merged: dict[str, CanonicalTag] = {tag.tag_id: tag for tag in base}
    for tag in extra:
        previous = merged.get(tag.tag_id)
        if previous is None:
            merged[tag.tag_id] = tag
            continue
        merged[tag.tag_id] = CanonicalTag(
            tag_id=tag.tag_id,
            name=previous.name or tag.name,
            groups=tuple(dict.fromkeys((*previous.groups, *tag.groups))),
            aliases=tuple(dict.fromkeys((*previous.aliases, *tag.aliases))),
            prototypes=tuple(
                dict.fromkeys((*previous.prototypes, *tag.prototypes))
            ),
        )
    return tuple(merged[tag_id] for tag_id in sorted(merged))


def load_seed_tags(
    seed_file: str | Path,
) -> tuple[tuple[CanonicalTag, ...], dict[str, str], dict[str, str]]:
    payload = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    tags = []
    packs = {}
    sources = {}
    for row in payload["tags"]:
        tag = CanonicalTag(
            tag_id=row["tag_id"],
            name=row["name"],
            groups=tuple(row["groups"]),
            aliases=tuple(row.get("aliases", ())),
            prototypes=tuple(row.get("prototypes", ())),
        )
        tags.append(tag)
        packs[tag.tag_id] = row["pack_id"]
        sources[tag.tag_id] = row.get("source", "bootstrap")
    return tuple(tags), packs, sources


__all__ = [
    "KnowledgeTagCandidate",
    "WorkplaceTagKnowledgeBase",
    "load_seed_tags",
    "merge_canonical_tags",
]
