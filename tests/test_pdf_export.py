import importlib.util
import unittest

from packages.domain.pdf_export import pdf_bytes


@unittest.skipUnless(importlib.util.find_spec("reportlab"), "install requirements-pdf.txt")
class PDFExportTests(unittest.TestCase):
    def test_generates_downloadable_pdf_with_cyrillic(self):
        data = pdf_bytes("# Sponsorship\n\n## Проверка отчёта\n\n- Кандидат и источник")
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertGreater(len(data), 1500)


if __name__ == "__main__":
    unittest.main()
