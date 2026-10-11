"""strip_exports on hand-built modules; the real engine is checked with node in CI."""
import unittest

import strip_exports as s


def module(exports, extra_sections=b""):
    body = s.uleb(len(exports)) + b"".join(
        s.uleb(len(n.encode())) + n.encode() + bytes([kind]) + s.uleb(index) for n, kind, index in exports)
    return s.MAGIC + extra_sections + bytes([7]) + s.uleb(len(body)) + body


# A custom section (id 0) placed before the export section, to check untouched copying.
CUSTOM = bytes([0]) + s.uleb(5) + s.uleb(4) + b"name"


class StripTests(unittest.TestCase):
    def test_keeps_memory_and_demo_exports_only(self):
        source = module([("memory", 2, 0), ("demo_open", 0, 3), ("kj_ops", 0, 4), ("demo_close", 0, 300)], CUSTOM)
        stripped, kept, removed = s.strip(source)
        self.assertEqual(kept, ["memory", "demo_open", "demo_close"])
        self.assertEqual(removed, ["kj_ops"])
        self.assertEqual(stripped, module([("memory", 2, 0), ("demo_open", 0, 3), ("demo_close", 0, 300)], CUSTOM))

    def test_round_trip_without_removals_is_identical(self):
        source = module([("memory", 2, 0), ("demo_init", 0, 1)], CUSTOM)
        self.assertEqual(s.strip(source)[0], source)

    def test_leb128_multi_byte_indices(self):
        for value in (0, 127, 128, 300, 624485, 2 ** 32 - 1):
            self.assertEqual(s.read_uleb(s.uleb(value), 0), (value, len(s.uleb(value))))

    def test_rejects_non_wasm_and_truncated(self):
        with self.assertRaises(ValueError):
            s.strip(b"not wasm")
        with self.assertRaises((ValueError, IndexError)):
            s.strip(module([("memory", 2, 0)])[:-1])


if __name__ == "__main__":
    unittest.main()
