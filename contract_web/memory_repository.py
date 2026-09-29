"""SQLite adapter for the existing OpenHarvey personal_memories table."""

from memory_core import MemoryRecord


class SQLiteMemoryRepository:
    """Use the host-owned SQLite connection and its current transaction."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def record(row):
        return MemoryRecord(**{key: row[key] for key in MemoryRecord.__dataclass_fields__}) if row else None

    def list(self, scope_id):
        return [self.record(row) for row in self.db.execute(
            'SELECT * FROM personal_memories WHERE user_id=? ORDER BY updated DESC,id', (scope_id,))]

    def get(self, scope_id, memory_id):
        return self.record(self.db.execute(
            'SELECT * FROM personal_memories WHERE id=? AND user_id=?', (memory_id, scope_id)).fetchone())

    def used_chars(self, scope_id):
        return self.db.execute("SELECT COALESCE(SUM(length(content)),0) FROM personal_memories WHERE user_id=? AND status='active'",
                               (scope_id,)).fetchone()[0]

    def insert(self, scope_id, record):
        self.db.execute('''INSERT INTO personal_memories
            (id,user_id,content,revision,created,updated,source,source_thread_id,source_message_id,status)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (record.id, scope_id, record.content, record.revision, record.created,
                         record.updated, record.source, record.source_thread_id, record.source_message_id,record.status))

    def replace(self, scope_id, record):
        self.db.execute('''UPDATE personal_memories SET content=?,revision=?,updated=?,source=?,
            source_thread_id=?,source_message_id=? WHERE id=? AND user_id=?''',
            (record.content, record.revision, record.updated, record.source,
             record.source_thread_id, record.source_message_id, record.id, scope_id))

    def delete(self, scope_id, memory_id):
        self.db.execute('DELETE FROM personal_memories WHERE id=? AND user_id=?', (memory_id, scope_id))
