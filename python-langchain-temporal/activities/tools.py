"""The EXECUTE TOOLS step: run tool calls against the Chinook database.

Business errors such as unknown customers or bad track IDs return as
model-visible tool results so the agent can explain them.
"""

import json

import db
from models.types import ToolRequest


def execute_tool(req: ToolRequest) -> str:
    name, args = req.call.name, req.call.args
    try:
        if name == "search_music":
            result = db.search_music(args["query"])
        elif name == "search_music_by_genre":
            result = db.search_music_by_genre(args["genre"])
        elif name == "search_music_by_artist":
            result = db.search_music_by_artist(args["artist"])
        elif name == "search_music_by_album":
            result = db.search_music_by_album(args["album"])
        elif name == "get_customer_orders":
            result = db.get_customer_orders(req.customer_email)
        elif name == "get_track_price":
            result = db.get_track_price(args["track_name"])
        elif name == "get_order_details":
            result = db.get_order_details(args["order_id"])
        elif name == "purchase_tracks":
            result = db.record_purchase(req.customer_email, args["track_ids"])
        else:
            raise ValueError(f"Unknown tool: {name}")
    except ValueError as e:
        return json.dumps({"error": str(e)})  # business error -> the model handles it
    return json.dumps(result, default=str)
