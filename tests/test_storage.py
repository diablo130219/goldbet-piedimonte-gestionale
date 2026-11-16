import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import PostgreSQLConnection

class FakeRaw:
    def __init__(self): self.queries=[]
    def execute(self,sql,params=()):
        self.queries.append((sql,params))
        return self

class PostgreSQLCompatibility(unittest.TestCase):
    def test_placeholder_translation_and_explicit_transactions(self):
        raw=FakeRaw()
        conn=PostgreSQLConnection(raw)
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('SELECT * FROM clients WHERE id=? AND first_name=?',(3,'Anna'))
        self.assertEqual(raw.queries,[('BEGIN',()),('SELECT * FROM clients WHERE id=%s AND first_name=%s',(3,'Anna'))])

    def test_schema_contains_two_cash_constraint_and_durable_logo(self):
        sql=(Path(__file__).resolve().parents[1]/'schema_postgres.sql').read_text()
        self.assertIn('CHECK(cash_number IN (1,2))',sql)
        self.assertIn('ux_active_shift_per_cash',sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS brand_assets',sql)

if __name__ == '__main__': unittest.main()