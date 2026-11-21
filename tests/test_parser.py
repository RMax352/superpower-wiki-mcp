"""Offline unit tests for wikitext parser and Pydantic input models."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from superpower_wiki_mcp.models import ComparePowersInput, GetLimitationsInput, SearchPowersInput
from superpower_wiki_mcp.parser import clean_wikitext, extract_power_links, truncate_text

SAMPLE_APPLICATIONS = """==Applications==
{{scroll box|
*[[Burning|Burn]] or [[Melting|melt]] things.
**[[Inflammation]]
*[[Heat Manipulation]] (with [[wikipedia:Thermodynamics|thermodynamics]]).
**[[Absolute Hot Inducement]]
***[[Incineration|Incinerate]] into [[Ash Transmutation|ash]]
*[[File:FireDemo.png|thumb|Ignored image]]
*[[Fanon:Broken Power]]
}}
{{Quote|Some flavor quote|Someone}}
<ref>Citation to drop</ref>
"""


class TestParserAndModels(unittest.TestCase):
    def test_clean_wikitext_unwraps_scroll_box_and_drops_noise(self) -> None:
        cleaned = clean_wikitext(SAMPLE_APPLICATIONS)
        self.assertIn("Burn or melt things.", cleaned)
        self.assertIn("  - Inflammation", cleaned)
        self.assertIn("    - Incinerate into ash", cleaned)
        self.assertIn("thermodynamics", cleaned)
        self.assertNotIn("scroll box", cleaned.lower())
        self.assertNotIn("File:FireDemo", cleaned)
        self.assertNotIn("Some flavor quote", cleaned)
        self.assertNotIn("Citation to drop", cleaned)

    def test_extract_power_links_filters_external_and_fanon(self) -> None:
        links = extract_power_links(SAMPLE_APPLICATIONS, include_fanon=False)
        titles = [item["title"] for item in links]
        self.assertIn("Burning", titles)
        self.assertIn("Melting", titles)
        self.assertIn("Heat Manipulation", titles)
        self.assertIn("Absolute Hot Inducement", titles)
        self.assertIn("Ash Transmutation", titles)
        self.assertTrue(all("wikipedia" not in t.lower() for t in titles))
        self.assertTrue(all("fanon:" not in t.lower() for t in titles))
        self.assertTrue(all("file:" not in t.lower() for t in titles))

        by_title = {item["title"]: item for item in links}
        self.assertEqual(by_title["Burning"]["depth"], 1)
        self.assertEqual(by_title["Inflammation"]["depth"], 2)
        self.assertEqual(by_title["Ash Transmutation"]["depth"], 3)

    def test_truncate_text_respects_budget(self) -> None:
        text = "\n".join(f"Line {i}" for i in range(200))
        cut, truncated = truncate_text(text, 200)
        self.assertTrue(truncated)
        self.assertLessEqual(len(cut), 200)

    def test_pydantic_models_validate_bounds(self) -> None:
        s = SearchPowersInput(query="  Fire Manipulation  ", limit=10)
        self.assertEqual(s.query, "Fire Manipulation")

        with self.assertRaises(ValidationError):
            ComparePowersInput(titles=["Only One"])

        with self.assertRaises(ValidationError):
            GetLimitationsInput(titles=["A", "B", "C", "D", "E", "F"])


if __name__ == "__main__":
    unittest.main()
