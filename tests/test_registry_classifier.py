import unittest

from registry_classifier import (
    classify_near_miss,
    classify_software_broad,
    classify_software_strict,
    mixed_it_bundle_signal,
)


class RegistryClassifierPhaseOneTests(unittest.TestCase):
    def test_mojibake_normalization_still_hits_software(self) -> None:
        row = {
            "objekti_procedurave": "MirÃ«mbajtje e softuerit pÃ«r portalin dixhital",
            "kodi_cpv_raw": "",
            "tipi_procedures": "",
        }
        broad_ok, _ = classify_software_broad(row)
        strict_ok, _, _ = classify_software_strict(row)
        self.assertTrue(broad_ok)
        self.assertTrue(strict_ok)

    def test_mixed_bundle_is_flagged_and_near_miss_reviewable(self) -> None:
        row = {
            "objekti_procedurave": "Zhvillim software dhe riparim printeresh",
            "kodi_cpv_raw": "72000000-5; 50312000-5",
            "tipi_procedures": "",
        }
        strict_ok, _, _ = classify_software_strict(row)
        mixed_ok, mixed_reasons = mixed_it_bundle_signal(row)
        near_ok, near_reasons = classify_near_miss(row)
        self.assertFalse(strict_ok)
        self.assertTrue(mixed_ok)
        self.assertTrue(any("kw:software" in r for r in mixed_reasons))
        self.assertTrue(near_ok)
        self.assertTrue(any(r.startswith("mixed_it_bundle:") for r in near_reasons))

    def test_near_miss_detects_soft_relevance_without_broad(self) -> None:
        row = {
            "objekti_procedurave": "Implementim sistemi elektronik per dokumente",
            "kodi_cpv_raw": "",
            "tipi_procedures": "",
        }
        broad_ok, _ = classify_software_broad(row)
        near_ok, near_reasons = classify_near_miss(row)
        self.assertFalse(broad_ok)
        self.assertTrue(near_ok)
        self.assertTrue(any(r.startswith("near_kw:") for r in near_reasons))


if __name__ == "__main__":
    unittest.main()
