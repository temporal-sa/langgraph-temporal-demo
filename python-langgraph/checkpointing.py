"""Secure serializer configuration shared by every Postgres checkpointer."""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def strict_checkpoint_serializer() -> JsonPlusSerializer:
    """Allow only LangGraph's built-in safe msgpack types on deserialization."""

    return JsonPlusSerializer(allowed_msgpack_modules=None)
