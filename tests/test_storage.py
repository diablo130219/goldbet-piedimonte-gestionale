import json, sys, unittest
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import PostgreSQLConnection
from server import shift_totals

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

    def test_explicit_sql_commit(self):
        raw=FakeRaw()
        conn=PostgreSQLConnection(raw)
        conn.execute('BEGIN IMMEDIATE')
        conn.commit()
        self.assertEqual(raw.queries[0][0], 'BEGIN')
        self.assertEqual(raw.queries[1][0], 'COMMIT')

    def test_postgres_numeric_aggregates_are_json_serializable(self):
        class FakeAggregateDb:
            def execute(self, sql, params=()):
                return self
            def fetchone(self):
                return {'credits': Decimal('8000'), 'debits': Decimal('1500')}

        shift = {'id': 13, 'green_cents': 289085, 'red_cents': 36137,
                 'initial_cents': 32525}
        result = shift_totals(FakeAggregateDb(), shift)
        self.assertEqual(result['blue_cents'], 252948)
        self.assertEqual(result['entries_cents'], 8000)
        self.assertEqual(result['exits_cents'], 1500)
        self.assertEqual(result['calculated_cents'], 291973)
        self.assertEqual(json.loads(json.dumps({'shift': result}))['shift'], result)
        self.assertIsInstance(result['entries_cents'], int)
        self.assertIsInstance(result['exits_cents'], int)

    def test_schema_contains_two_cash_constraint_and_durable_logo(self):
        sql=(Path(__file__).resolve().parents[1]/'schema_postgres.sql').read_text()
        self.assertIn('CHECK(cash_number IN (1,2))',sql)
        self.assertIn('ux_active_shift_per_cash',sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS brand_assets',sql)

if __name__ == '__main__': unittest.main()