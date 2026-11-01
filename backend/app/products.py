"""The product index: the app's own catalogue plus the shop's sale listings.

Two files, on purpose:

  app/catalog.json   the 25 products the app already knows, each now carrying `aimed_at`
                     (what the product's own claims are aimed at, in YouCam concern names).
  app/store.json     the "Glowcart Big Sale" listings and the extra products the demo persona's
                     history refers to. A shop's inventory is the shop's, not the app's.

Both are read into one index, because every engine (decision, patterns, cartcheck, triage) works
on `decision.Product` and should not care where a product came from. `decision.load_catalog()`
still reads catalog.json on its own, so anything measuring the app's own catalogue is unchanged.

Prices: `price_inr` is the normal price and is what new spend is worked out from. A sale listing
adds `sale_price_inr`, which is only ever shown next to it, never used to decide anything.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .decision import CATALOG_PATH, Product, load_catalog

STORE_PATH = Path(__file__).parent / "store.json"


@lru_cache(maxsize=4)
def _store(path: str | None = None) -> dict:
    return json.loads(Path(path or STORE_PATH).read_text(encoding="utf-8"))


_PRODUCT_FIELDS = set(Product.__dataclass_fields__)


def store_products(path: str | None = None) -> dict[str, Product]:
    # The `shop` block is the shop's own tagging for the basket, not part of a product's label.
    return {r["id"]: Product(**{k: v for k, v in r.items() if k in _PRODUCT_FIELDS})
            for r in _store(path)["products"]}


def shop_tags(path: str | None = None) -> dict[str, dict]:
    """product id -> the shop's tags (job, suits, texture, finish, tinted, shades). Basket only."""
    return {r["id"]: dict(r["shop"]) for r in _store(path)["products"] if r.get("shop")}


def index(catalog_path: Path | None = None, store_path: str | None = None) -> dict[str, Product]:
    """Every product the app can check, by id. Catalogue first, then the shop's own stock."""
    out = dict(load_catalog(catalog_path or CATALOG_PATH))
    out.update(store_products(store_path))
    return out


def sale(path: str | None = None) -> dict:
    """The sale as the store page shows it: its name, its line, and its listings in order.

    Each listing carries the product id, its sale price and the shop's own blurb. The blurb is
    marketing copy from a fictional shop; derm//os never treats it as evidence, which is exactly
    the point the store page makes.
    """
    s = _store(path)
    return {"name": s["sale"]["name"], "line": s["sale"]["line"],
            "items": [dict(i) for i in s["sale"]["items"]]}


def sale_price(product_id: str, path: str | None = None) -> int | None:
    return next((i["sale_price_inr"] for i in sale(path)["items"] if i["product_id"] == product_id), None)
