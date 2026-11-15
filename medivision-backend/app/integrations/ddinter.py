"""
DDInter 2.0 SQLite client — drug-drug interaction database.

Sourced from SPerekrestova/pillchecker-api (MIT). The actual SQLite database
file is NOT bundled (it is built by a setup script that downloads CSVs from
the DDInter website — see setup_integrations.py).

When the DB is present:
  - available() returns True
  - check_pair(drug_a, drug_b) returns a real interaction level + evidence URL
  - check_drug(drug) returns all known interactions for a single drug

When the DB is absent:
  - available() returns False
  - all calls return None / empty lists
  - callers fall back to OpenFDA interactions or the rule-based safety.py

Build the DB once (takes ~3-5 minutes, downloads ~50 MB of CSVs):

    python -m medivision-backend.integrations.setup_integrations build-ddinter

Or:

    cd medivision-backend && python -m integrations.setup_integrations build-ddinter
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DATA_DIR / "ddinter.db")

_conn: sqlite3.Connection | None = None
_tried_connect = False


def available() -> bool:
    return Path(DB_PATH).exists()


def _connect() -> sqlite3.Connection | None:
    global _conn, _tried_connect
    if _conn is not None:
        return _conn
    if _tried_connect:
        return None
    _tried_connect = True
    if not Path(DB_PATH).exists():
        return None
    try:
        # Open read-only immutable for safety + concurrent reads from the API.
        uri = f"file:{DB_PATH}?mode=ro&immutable=1"
        _conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        return _conn
    except Exception:
        _conn = None
        return None


def row_count() -> int:
    conn = _connect()
    if conn is None:
        return 0
    try:
        cur = conn.execute("SELECT COUNT(*) FROM interactions")
        return int(cur.fetchone()[0])
    except Exception:
        # Table name might differ; try a couple of common ones
        for tbl in ("interactions", "ddinter", "drug_interactions"):
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {tbl}")
                return int(cur.fetchone()[0])
            except Exception:
                continue
        return 0


SYNONYMS: dict[str, str] = {
    "aspirin": "acetylsalicylic acid",
    "paracetamol": "acetaminophen",
    "tylenol": "acetaminophen",
    "dolo": "acetaminophen",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
}


def _find_drug_id(conn: sqlite3.Connection, drug_name: str) -> str | None:
    """Try several table layouts; pillchecker's schema uses ddinter_id + name."""
    drug = drug_name.strip().lower()
    if not drug:
        return None
    search_terms = [drug]
    if drug in SYNONYMS and SYNONYMS[drug] not in search_terms:
        search_terms.append(SYNONYMS[drug])

    # Try exact + LIKE match across plausible tables/columns
    queries = [
        "SELECT ddinter_id FROM drugs WHERE LOWER(name) = ? OR LOWER(name) LIKE ? LIMIT 1",
        "SELECT id FROM drugs WHERE LOWER(name) = ? OR LOWER(name) LIKE ? LIMIT 1",
        "SELECT drug_id FROM drugs WHERE LOWER(name) = ? OR LOWER(name) LIKE ? LIMIT 1",
        "SELECT ddinter_id FROM drug_names_fts WHERE name MATCH ? LIMIT 1",
    ]
    for term in search_terms:
        pat = f"%{term}%"
        for q in queries:
            try:
                cur = conn.execute(q, (term, pat) if q.count("?") == 2 else (term,))
                row = cur.fetchone()
                if row:
                    return str(row[0])
            except Exception:
                continue
    return None


def check_pair(drug_a: str, drug_b: str) -> dict[str, Any] | None:
    """Returns the interaction row between two drugs, or None.

    Output shape:
      {"drugA": "...", "drugB": "...", "level": "Major" | "Moderate" | "Minor" | "Unknown",
       "effect": "...", "mechanism": "...", "source": "DDInter 2.0",
       "url": "https://www.ddinter.cn/interactions/..."}
    """
    conn = _connect()
    if conn is None or not drug_a or not drug_b:
        return None
    a_id = _find_drug_id(conn, drug_a)
    b_id = _find_drug_id(conn, drug_b)
    if not a_id or not b_id:
        return None
    # Try common interaction-table schemas
    queries = [
        """SELECT level, effect, mechanism FROM interactions
           WHERE (ddinter_id_a = ? AND ddinter_id_b = ?)
              OR (ddinter_id_a = ? AND ddinter_id_b = ?) LIMIT 1""",
        """SELECT severity AS level, COALESCE(effect, description, '') AS effect, COALESCE(mechanism, '') AS mechanism
           FROM interactions
           WHERE (drug_a_id = ? AND drug_b_id = ?)
              OR (drug_a_id = ? AND drug_b_id = ?) LIMIT 1""",
    ]
    for q in queries:
        try:
            cur = conn.execute(q, (a_id, b_id, b_id, a_id))
            row = cur.fetchone()
            if row:
                col_keys = row.keys()
                lvl = "Unknown"
                if "level" in col_keys and row["level"]:
                    lvl = str(row["level"])
                elif "severity" in col_keys and row["severity"]:
                    lvl = str(row["severity"])

                eff = str(row["effect"]) if "effect" in col_keys and row["effect"] else ""
                mech = str(row["mechanism"]) if "mechanism" in col_keys and row["mechanism"] else ""

                return {
                    "drugA": drug_a,
                    "drugB": drug_b,
                    "level": lvl,
                    "effect": eff,
                    "mechanism": mech,
                    "source": "DDInter 2.0",
                    "url": f"https://www.ddinter.cn/interactions/{a_id}-{b_id}",
                }
        except Exception:
            continue
    return None


def check_drug(drug_name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Returns all known interactions for a single drug."""
    conn = _connect()
    if conn is None or not drug_name:
        return []
    drug_id = _find_drug_id(conn, drug_name)
    if not drug_id:
        return []
    queries = [
        """SELECT other_drug_name AS other, level, effect FROM interactions
           WHERE ddinter_id_a = ? OR ddinter_id_b = ? LIMIT ?""",
        """SELECT drug_b_name AS other, severity AS level, description AS effect
           FROM interactions WHERE drug_a_id = ? LIMIT ?""",
    ]
    for q in queries:
        try:
            cur = conn.execute(q, (drug_id, drug_id, limit))
            return [{
                "drug": drug_name,
                "otherDrug": str(r["other"]),
                "level": str(r["level"] or "Unknown"),
                "effect": str(r["effect"] or ""),
                "source": "DDInter 2.0",
            } for r in cur.fetchall()]
        except Exception:
            continue
    return []
