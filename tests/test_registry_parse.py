import unittest

from bs4 import BeautifulSoup

from registry_parse import next_page_payload


class RegistryParseTests(unittest.TestCase):
    def test_next_page_payload_reads_required_fields(self) -> None:
        html = """
        <form action="/regjistri-i-parashikimeve/">
          <input name="__RequestVerificationToken" value="abc123" />
          <input name="ufprt" value="tok456" />
        </form>
        """
        form = BeautifulSoup(html, "html.parser").find("form")
        payload = next_page_payload(form)
        self.assertEqual(payload["__RequestVerificationToken"], "abc123")
        self.assertEqual(payload["ufprt"], "tok456")

    def test_next_page_payload_errors_on_missing_token(self) -> None:
        html = """
        <form action="/regjistri-i-parashikimeve/">
          <input name="ufprt" value="tok456" />
        </form>
        """
        form = BeautifulSoup(html, "html.parser").find("form")
        with self.assertRaises(ValueError):
            next_page_payload(form)


if __name__ == "__main__":
    unittest.main()
