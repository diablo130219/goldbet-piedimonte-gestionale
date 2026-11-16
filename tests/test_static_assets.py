"""Regression checks: every stylesheet loads and polling does not flicker."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'static'

class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.styles=[]
        self.scripts=[]
    def handle_starttag(self, tag, attrs):
        attr=dict(attrs)
        if tag=='link' and attr.get('rel')=='stylesheet':
            self.styles.append(attr.get('href'))
        if tag=='script':
            self.scripts.append(attr.get('src'))

class StaticAssetDelivery(unittest.TestCase):
    def test_each_css_file_has_its_own_valid_link(self):
        parser=AssetParser()
        parser.feed((ROOT/'index.html').read_text(encoding='utf8'))
        self.assertEqual(len(parser.styles),4)
        for name in ('styles.css','premium.css','impact.css','signature.css'):
            matches=[url for url in parser.styles if url and f'/static/{name}?v=' in url]
            self.assertEqual(len(matches),1,f'{name} must load as its own stylesheet')
            self.assertTrue((ROOT/name).is_file())
    def test_versioned_app_script_and_silent_poll(self):
        parser=AssetParser()
        parser.feed((ROOT/'index.html').read_text(encoding='utf8'))
        self.assertEqual(len(parser.scripts),1)
        self.assertIn('app.js?v=',parser.scripts[0])
        code=(ROOT/'app.js').read_text(encoding='utf8')
        self.assertIn('async function pollLiveData()',code)
        self.assertIn('if(previous===next)return;',code)
        self.assertIn('document.hidden',code)
        self.assertNotIn('},3000);\ninit();',code)

if __name__=='__main__':unittest.main()