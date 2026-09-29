"""The memory domain must run without an OpenHarvey database or web app."""
import unittest

from memory_core import (InvalidContent, LimitReached, MemoryPolicy, MemoryProvenance,
                         MemoryService, MissingMemory, RevisionConflict)


class InMemoryRepository:
    def __init__(self): self.rows={}

    def list(self,scope_id):
        return sorted((row for (scope,_),row in self.rows.items() if scope==scope_id),
                      key=lambda row:(-row.updated,row.id))

    def get(self,scope_id,memory_id):return self.rows.get((scope_id,memory_id))
    def used_chars(self,scope_id):return sum(len(row.content) for row in self.list(scope_id))
    def insert(self,scope_id,record):self.rows[scope_id,record.id]=record
    def replace(self,scope_id,record):self.rows[scope_id,record.id]=record
    def delete(self,scope_id,memory_id):del self.rows[scope_id,memory_id]


class MemoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.repo=InMemoryRepository()
        ids=iter(['a'*24,'b'*24,'c'*24])
        self.service=MemoryService(self.repo,MemoryPolicy(item_limit=8,total_limit=12),new_id=lambda:next(ids),now=lambda:42.0)

    def test_scopes_snapshot_and_provenance(self):
        mine=self.service.create('user-a',' concise ',MemoryProvenance('conversation','thread-1','msg-1'))
        self.assertEqual(mine.id,'a'*24)
        self.assertEqual(mine.content,'concise')
        self.assertEqual((mine.source,mine.source_thread_id,mine.source_message_id),('conversation','thread-1','msg-1'))
        self.assertEqual(self.service.snapshot('user-a',False),())
        self.assertEqual(self.service.snapshot('user-a',True),(mine,))
        self.assertEqual(self.service.snapshot('user-b',True),())
        with self.assertRaises(MissingMemory):self.service.update('user-b',mine.id,1,'other')

    def test_create_update_delete_and_conflicts(self):
        first=self.service.create('user-a','short')
        updated=self.service.update('user-a',first.id,1,'new')
        self.assertEqual((updated.revision,updated.created,updated.source),(2,first.created,'manual'))
        with self.assertRaises(RevisionConflict):self.service.update('user-a',first.id,1,'stale')
        with self.assertRaises(RevisionConflict):self.service.delete('user-a',first.id,True)
        self.assertEqual(self.service.delete('user-a',first.id,2),updated)
        self.assertEqual(self.service.list('user-a'),[])

    def test_item_and_total_limits_do_not_mutate_existing_records(self):
        first=self.service.create('user-a','12345678')
        second=self.service.create('user-a','1234')
        with self.assertRaises(LimitReached):self.service.create('user-a','x')
        with self.assertRaises(LimitReached):self.service.update('user-a',second.id,1,'12345')
        with self.assertRaises(InvalidContent):self.service.update('user-a',first.id,1,'\x00')
        with self.assertRaises(InvalidContent):self.service.create('user-a','123456789')
        self.assertEqual(self.repo.get('user-a',first.id),first)


if __name__=='__main__':unittest.main()
