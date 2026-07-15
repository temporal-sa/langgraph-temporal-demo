"""Runtime adapter for the shared Chinook catalog and order queries."""

from support_agent_common import database

import config


def search_music(query: str) -> list[dict]:
    return database.search_music(config.DB_URL, query)


def search_music_by_genre(genre: str) -> list[dict]:
    return database.search_music_by_genre(config.DB_URL, genre)


def search_music_by_album(album: str) -> list[dict]:
    return database.search_music_by_album(config.DB_URL, album)


def search_music_by_artist(artist: str) -> list[dict]:
    return database.search_music_by_artist(config.DB_URL, artist)


def get_track_price(track_name: str) -> list[dict]:
    return database.get_track_price(config.DB_URL, track_name)


def get_customer_orders(email: str) -> list[dict]:
    return database.get_customer_orders(config.DB_URL, email)


def get_order_details(order_id: int) -> list[dict]:
    return database.get_order_details(config.DB_URL, order_id)


def record_purchase(
    email: str, track_ids: list[int], *, idempotency_key: str
) -> dict:
    return database.record_purchase(
        config.DB_URL,
        email,
        track_ids,
        idempotency_key=idempotency_key,
    )
