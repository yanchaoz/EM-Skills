import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "vem_dataset_catalog.py"
SPEC = importlib.util.spec_from_file_location("vem_dataset_catalog", SCRIPT_PATH)
catalog_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(catalog_module)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog_module.load_catalog()

    def test_bundled_catalog_validates(self):
        self.assertEqual(catalog_module.validate_catalog(self.catalog), [])

    def test_strict_mouse_cortex_neuron_query(self):
        results = catalog_module.query_catalog(
            self.catalog,
            {
                "species": "mouse",
                "tissue": "cortex",
                "max_xy_nm": 10,
                "annotations": ["neuron_instance"],
                "require_labels": True,
            },
        )
        ids = {record["id"] for record in results}
        self.assertIn("snemi3d-ac3-ac4", ids)
        self.assertIn("microns-pinky", ids)
        self.assertNotIn("isbi-2012", ids)

    def test_unknown_resolution_fails_strict_resolution_filter(self):
        strict = catalog_module.query_catalog(
            self.catalog,
            {"annotations": ["neuron_instance"], "max_xy_nm": 10},
        )
        exploratory = catalog_module.query_catalog(
            self.catalog,
            {
                "annotations": ["neuron_instance"],
                "max_xy_nm": 10,
                "include_unknown_resolution": True,
            },
        )
        self.assertNotIn("emneuron", {record["id"] for record in strict})
        self.assertIn("emneuron", {record["id"] for record in exploratory})

    def test_manifest_preserves_authorization_boundary(self):
        manifest = catalog_module.build_manifest(
            self.catalog, "snemi3d-ac3-ac4", "segneuron-inference"
        )
        self.assertEqual(manifest["handoff"]["compatibility"], "candidate")
        self.assertFalse(manifest["handoff"]["execution_authorized"])
        self.assertIn("dataset_license", manifest["handoff"]["unresolved_fields"])
        self.assertTrue(any("transfer size" in item for item in manifest["handoff"]["required_checks"]))

    def test_cli_writes_json_shortlist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "shortlist.json"
            status = catalog_module.main(
                [
                    "query",
                    "--annotation",
                    "mitochondria_instance",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertGreaterEqual(payload["result_count"], 2)
            self.assertIn("mitoem", {record["id"] for record in payload["results"]})


if __name__ == "__main__":
    unittest.main()
