"""Live integration tests against powerlisting.fandom.com MediaWiki API."""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("SUPERPOWER_MCP_FORCE_IPV4", "1")

from superpower_wiki_mcp.models import ResponseFormat
from superpower_wiki_mcp.server import (
    superpower_browse_category,
    superpower_compare_powers,
    superpower_explore_tree,
    superpower_get_limitations,
    superpower_get_power,
    superpower_get_section,
    superpower_random_powers,
    superpower_search,
)


class TestSuperpowerWikiIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_search_excludes_fanon_by_default(self) -> None:
        raw = await superpower_search(query="Fire Manipulation", limit=5, response_format=ResponseFormat.JSON)
        data = json.loads(raw)
        self.assertGreater(data["count"], 0)
        self.assertTrue(all(item["namespace"] == 0 for item in data["items"]))

    async def test_get_power_resolves_redirect_and_skips_known_users(self) -> None:
        raw = await superpower_get_power(title="Pyrokinesis", response_format=ResponseFormat.JSON)
        data = json.loads(raw)
        self.assertEqual(data["title"], "Fire Manipulation")
        self.assertEqual(data["redirected_from"], "Pyrokinesis")
        self.assertIn("Capabilities", data["sections"])
        self.assertIn("Limitations", data["sections"])
        self.assertNotIn("Known Users", data["sections"])

    async def test_get_section_specific(self) -> None:
        md = await superpower_get_section(title="Fire Manipulation", section="Limitations")
        self.assertIn("# Fire Manipulation", md)
        self.assertIn("Limitations", md)

    async def test_explore_tree_returns_applications_and_variations(self) -> None:
        raw = await superpower_explore_tree(title="Fire Manipulation", response_format=ResponseFormat.JSON)
        data = json.loads(raw)
        self.assertEqual(data["title"], "Fire Manipulation")
        self.assertIn("Applications", data["tree"])
        self.assertGreaterEqual(len(data["tree"]["Applications"]), 5)

    async def test_get_limitations_parallel(self) -> None:
        raw = await superpower_get_limitations(
            titles=["Fire Manipulation", "Ice Manipulation"],
            response_format=ResponseFormat.JSON,
        )
        data = json.loads(raw)
        self.assertEqual(len(data["results"]), 2)
        self.assertTrue(all(r["error"] is None and r["limitations"] for r in data["results"]))

    async def test_browse_category_and_random(self) -> None:
        cat_raw = await superpower_browse_category(
            category="Elemental Manipulation",
            limit=10,
            response_format=ResponseFormat.JSON,
        )
        cat_data = json.loads(cat_raw)
        self.assertGreater(len(cat_data["powers"]), 0)

        rand_raw = await superpower_random_powers(
            count=2,
            include_summary=True,
            response_format=ResponseFormat.JSON,
        )
        rand_data = json.loads(rand_raw)
        self.assertEqual(rand_data["count"], 2)

    async def test_compare_powers(self) -> None:
        raw = await superpower_compare_powers(
            titles=["Fire Manipulation", "Ice Manipulation"],
            response_format=ResponseFormat.JSON,
        )
        data = json.loads(raw)
        self.assertEqual(len(data["powers"]), 2)
        self.assertIn("Elemental Manipulation", data["shared_categories"])


if __name__ == "__main__":
    unittest.main()
