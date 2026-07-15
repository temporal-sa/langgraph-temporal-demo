"""Parameterized Chinook queries shared by every support-agent runtime."""

from typing import Any

import psycopg
from psycopg.rows import dict_row


def _connect(db_url: str):
    return psycopg.connect(db_url, row_factory=dict_row)


def search_music(db_url: str, query: str) -> list[dict[str, Any]]:
    return _search_tracks(
        db_url,
        "t.name ILIKE %(q)s OR ar.name ILIKE %(q)s OR al.title ILIKE %(q)s",
        {"q": f"%{query}%"},
    )


def search_music_by_genre(db_url: str, genre: str) -> list[dict[str, Any]]:
    return _search_tracks(
        db_url,
        "g.name ILIKE %(q)s",
        {"q": f"%{genre}%"},
        extra_join="JOIN genre g ON g.genre_id = t.genre_id",
    )


def search_music_by_album(db_url: str, album: str) -> list[dict[str, Any]]:
    return _search_tracks(db_url, "al.title ILIKE %(q)s", {"q": f"%{album}%"})


def search_music_by_artist(db_url: str, artist: str) -> list[dict[str, Any]]:
    return _search_tracks(db_url, "ar.name ILIKE %(q)s", {"q": f"%{artist}%"})


def _search_tracks(
    db_url: str, where: str, params: dict[str, object], *, extra_join: str = ""
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        {extra_join}
        WHERE {where}
        ORDER BY ar.name, al.title, t.track_id
        LIMIT 15
    """
    with _connect(db_url) as conn:
        return conn.execute(sql, params).fetchall()


def get_track_price(db_url: str, track_name: str) -> list[dict[str, Any]]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE t.name ILIKE %(name)s
        ORDER BY t.track_id
        LIMIT 5
    """
    with _connect(db_url) as conn:
        return conn.execute(sql, {"name": f"%{track_name}%"}).fetchall()


def get_customer_orders(db_url: str, email: str) -> list[dict[str, Any]]:
    sql = """
        SELECT i.invoice_id, i.invoice_date::date::text AS date,
               i.total::float8 AS total, count(l.invoice_line_id)::int AS track_count
        FROM invoice i
        JOIN customer c ON c.customer_id = i.customer_id
        LEFT JOIN invoice_line l ON l.invoice_id = i.invoice_id
        WHERE c.email = %(email)s
        GROUP BY i.invoice_id, i.invoice_date, i.total
        ORDER BY i.invoice_date DESC, i.invoice_id DESC
        LIMIT 10
    """
    with _connect(db_url) as conn:
        return conn.execute(sql, {"email": email}).fetchall()


def get_order_details(db_url: str, order_id: int) -> list[dict[str, Any]]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               l.unit_price::float8 AS price, l.quantity
        FROM invoice_line l
        JOIN track t ON t.track_id = l.track_id
        LEFT JOIN album al ON al.album_id = t.album_id
        LEFT JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE l.invoice_id = %(order_id)s
        ORDER BY l.invoice_line_id
    """
    with _connect(db_url) as conn:
        return conn.execute(sql, {"order_id": order_id}).fetchall()


def record_purchase(
    db_url: str,
    email: str,
    track_ids: list[int],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create one invoice per durable tool execution.

    The idempotency row is inserted in the same transaction as the invoice. A
    concurrent retry blocks on the unique key, then reads the committed invoice
    instead of inserting a second purchase.
    """

    if not idempotency_key:
        raise ValueError("A purchase idempotency key is required")

    with _connect(db_url) as conn:
        # Serialize the one-time schema bootstrap and Chinook's explicit
        # max()+1 ID allocation. This demo favors correctness over purchase
        # throughput, and the transaction lock spans all related inserts.
        conn.execute("SELECT pg_advisory_xact_lock(20260715, 1)")
        _ensure_purchase_idempotency_table(conn)
        claimed = conn.execute(
            """INSERT INTO purchase_idempotency (idempotency_key)
               VALUES (%s)
               ON CONFLICT (idempotency_key) DO NOTHING
               RETURNING idempotency_key""",
            (idempotency_key,),
        ).fetchone()
        if claimed is None:
            existing = conn.execute(
                """SELECT invoice_id FROM purchase_idempotency
                   WHERE idempotency_key = %s""",
                (idempotency_key,),
            ).fetchone()
            if not existing or existing["invoice_id"] is None:
                raise RuntimeError("Purchase idempotency record has no invoice")
            return _purchase_result(conn, existing["invoice_id"])

        customer = conn.execute(
            """SELECT customer_id, address, city, state, country, postal_code
               FROM customer WHERE email = %s""",
            (email,),
        ).fetchone()
        if not customer:
            raise ValueError(f"No customer account found for {email}")

        tracks = conn.execute(
            """SELECT track_id, name, unit_price FROM track
               WHERE track_id = ANY(%s) ORDER BY track_id""",
            (track_ids,),
        ).fetchall()
        if not tracks:
            raise ValueError(f"No tracks found for IDs {track_ids}")

        total = sum(track["unit_price"] for track in tracks)
        invoice_id = conn.execute(
            "SELECT coalesce(max(invoice_id), 0) + 1 AS id FROM invoice"
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO invoice (invoice_id, customer_id, invoice_date, billing_address,
                                    billing_city, billing_state, billing_country,
                                    billing_postal_code, total)
               VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s)""",
            (
                invoice_id,
                customer["customer_id"],
                customer["address"],
                customer["city"],
                customer["state"],
                customer["country"],
                customer["postal_code"],
                total,
            ),
        )
        line_id = conn.execute(
            "SELECT coalesce(max(invoice_line_id), 0) AS id FROM invoice_line"
        ).fetchone()["id"]
        for track in tracks:
            line_id += 1
            conn.execute(
                """INSERT INTO invoice_line (invoice_line_id, invoice_id, track_id,
                                             unit_price, quantity)
                   VALUES (%s, %s, %s, %s, 1)""",
                (line_id, invoice_id, track["track_id"], track["unit_price"]),
            )

        conn.execute(
            """UPDATE purchase_idempotency SET invoice_id = %s
               WHERE idempotency_key = %s""",
            (invoice_id, idempotency_key),
        )

        return {
            "invoice_id": invoice_id,
            "tracks": [
                {
                    "track_id": track["track_id"],
                    "name": track["name"],
                    "price": float(track["unit_price"]),
                }
                for track in tracks
            ],
            "total": float(total),
        }


def _ensure_purchase_idempotency_table(conn) -> None:
    # CREATE IF NOT EXISTS keeps existing demo databases upgradeable without a
    # separate migration step. Fresh databases also create this in chinook.sql.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS purchase_idempotency (
               idempotency_key TEXT PRIMARY KEY,
               invoice_id INT UNIQUE REFERENCES invoice(invoice_id)
           )"""
    )


def _purchase_result(conn, invoice_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT i.invoice_id, i.total, t.track_id, t.name, l.unit_price
           FROM invoice i
           JOIN invoice_line l ON l.invoice_id = i.invoice_id
           JOIN track t ON t.track_id = l.track_id
           WHERE i.invoice_id = %s
           ORDER BY l.invoice_line_id""",
        (invoice_id,),
    ).fetchall()
    if not rows:
        raise RuntimeError(f"Invoice {invoice_id} has no purchase lines")
    return {
        "invoice_id": invoice_id,
        "tracks": [
            {
                "track_id": row["track_id"],
                "name": row["name"],
                "price": float(row["unit_price"]),
            }
            for row in rows
        ],
        "total": float(rows[0]["total"]),
    }
