import unittest
import sys
import os

from basic_testcase import FourcatTestCase


class TestJobQueue(FourcatTestCase):
	example_record = {
		"jobtype": "test",
		"remote_id": "1234",
		"details": "",
		"claimed": 0,
		"claim_after": 0,
		"attempts": 0
	}

	@unittest.expectedFailure
	def test_insert_failure(self):
		self.db.insert("jobs", {})

	def test_execute(self):
		"""
		Test query execution

		Expected: Afterwards, database contains one record
		"""
		self.db.execute("INSERT INTO jobs (jobtype, remote_id) VALUES (%s, %s)", ("test", "1234"))
		jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs")["num"]
		self.assertEqual(jobs, 1)

	def test_fetchone(self):
		"""
		Test fetching a single row

		Expected: One row returned, with the correct values
		"""
		self.db.insert("jobs", self.example_record)
		data = self.db.fetchone("SELECT * FROM jobs")

		for field in self.example_record:
			with self.subTest(field=field):
				self.assertEqual(data[field], self.example_record[field])

	def test_fetchall(self):
		"""
		Test fetching multiple rows

		Expected: Multiple rows are returned, with the correct values
		"""
		amount = 100
		records = []
		record_id = int(self.example_record["remote_id"])
		for i in range(0, amount):
			record = self.example_record.copy()
			record["remote_id"] = str(record_id)
			self.db.insert("jobs", record)
			records.append(record)
			record_id += 1

		stored = self.db.fetchall("SELECT * FROM jobs ORDER BY remote_id ASC")
		for i in range(0, amount):
			row = stored.pop()
			record = records.pop()
			for field in record:
				with self.subTest(field=field):
					self.assertEqual(record[field], row[field])

	def test_insert(self):
		"""
		Test insert convenience method

		Expected: Supplied data is inserted and can be retrieved
		"""
		job = {
			"jobtype": "test",
			"remote_id": 1234,
			"details": ""
		}

		expected = self.example_record
		rows = self.db.insert("jobs", job)
		with self.subTest("numrows"):
			self.assertEqual(rows, 1)

		data = self.db.fetchone("SELECT * FROM jobs")
		for field in expected:
			with self.subTest(field=field):
				self.assertEqual(data[field], expected[field])

	def test_update(self):
		"""
		Test update convenience method

		Expected: Data is updated and can be retrieved
		"""
		self.db.insert("jobs", self.example_record)
		rows = self.db.update("jobs", data={"details": "success"})
		with self.subTest("numrows"):
			self.assertEqual(rows, 1)

		job = self.db.fetchone("SELECT * FROM jobs")
		self.assertIsNotNone(job)
		self.assertEqual(job["details"], "success")

	def test_update_where(self):
		"""
		Test update convenience method with WHERE clause

		Expected: Only the rows matching the WHERE data are updated
		"""
		copy = self.example_record.copy()
		copy["remote_id"] += "a"
		self.db.insert("jobs", self.example_record)
		self.db.insert("jobs", copy)

		rows = self.db.update("jobs", data={"details": "success"},
							  where={"remote_id": self.example_record["remote_id"]})
		with self.subTest("numrows"):
			self.assertEqual(rows, 1)

		jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs WHERE details = %s", ("success",))["num"]
		self.assertEqual(jobs, 1)

	def test_delete(self):
		"""
		Test deletion convenience method

		Expected: Only the rows matching the parameters are deleted
		"""
		copy = self.example_record.copy()
		copy["remote_id"] += "a"
		self.db.insert("jobs", self.example_record)
		self.db.insert("jobs", copy)

		rows = self.db.delete("jobs", where={"remote_id": self.example_record["remote_id"]})
		with self.subTest("numrows"):
			self.assertEqual(rows, 1)

		jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs")["num"]
		self.assertEqual(jobs, 1)

	@unittest.expectedFailure
	def test_insert_unsafe(self):
		"""
		Test inserting a duplicate row where a constraint forbids this

		Expected: Test fails
		"""
		self.db.insert("jobs", self.example_record)
		self.db.insert("jobs", self.example_record)

	def test_insert_safe(self):
		"""
		Test inserting a duplicate row with the 'safe' parameter set

		Expected: No failure, but only one row is inserted
		"""
		self.db.insert("jobs", self.example_record, safe=True)
		self.db.insert("jobs", self.example_record, safe=True)

		jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs")["num"]
		self.assertEqual(jobs, 1)

	def test_transaction_rollback(self):
		"""
		Test rolling back a transaction

		Expected: No data is inserted, because the transaction is rolled back before committing
		"""
		copy = self.example_record.copy()
		copy["remote_id"] += "a"

		self.db.insert("jobs", self.example_record, commit=False)
		self.db.insert("jobs", copy, commit=False)
		self.db.rollback()
		self.db.commit()

		jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs")["num"]
		self.assertEqual(jobs, 0)


if __name__ == '__main__':
	unittest.main()
