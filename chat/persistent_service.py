import abc, binascii, datetime
import psycopg2

UNIXTIME_ORIGIN = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

class PersistentServiceBase(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self, config): pass

    # メッセージを保存する．戻り値はメッセージのユニークID
    @abc.abstractmethod
    def store(self, uid, date, name, color, icon_hash, body): pass

    # 最新のcount件を取得する．戻り値は規定したJSONと同じ辞書形式
    @abc.abstractmethod
    def fetch_latest(self, count, min_id = None): pass

    # アイコンバイナリを保存する．戻り値無し．
    # 既にエントリが存在する場合は，descriptionのみ更新
    @abc.abstractmethod
    def store_icon(self, uid, icon_hash, icon_bin, icon_mime, description): pass

    # アイコンバイナリを取得. (binary, mime)のタプルを返却．(None,None)なら合致なし
    @abc.abstractmethod
    def fetch_icon(self, icon_hash): pass

class PsycopgPersistentService(PersistentServiceBase):
    def __init__(self, config):
        self.db_name = config.get('db_name', None)
        self.db_user = config.get('db_user', None)
        self.db_pass = config.get('db_pass', None)
        self.db_host = config.get('db_host', 'localhost')

    def open_db(self):
        return psycopg2.connect(database=self.db_name, user=self.db_user, password=self.db_pass, host=self.db_host)

    def dbrow_to_json(self, row):
        dt = row[1]
        icon_hash = None
        if dt.tzinfo: dt = dt.astimezone(datetime.timezone.utc)
        if row[4]: icon_hash = binascii.b2a_hex(row[4]).decode('ascii')
        return {'i': row[0], 'd': int((dt - UNIXTIME_ORIGIN).total_seconds() * 1000),
                'n': row[2], 'c': row[3], 'g': icon_hash, 't': row[5]}

    def store(self, uid, date, name, color, icon_hash, body):
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('INSERT INTO messages (date, uid, name, color, icon, body) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
                             (date, uid, name, color, icon_hash, body))
                conn.commit()
                return cur.fetchone()[0]

    def fetch_latest(self, count, min_id = None):
        if not min_id: min_id = -1
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT * FROM (SELECT id, date, name, color, icon, body FROM messages WHERE id > %s ORDER BY id DESC LIMIT %s) AS TMP
                               ORDER BY date DESC LIMIT %s''', (min_id, count + 16, count))
                return [self.dbrow_to_json(x) for x in cur.fetchall()]

    def store_icon(self, uid, icon_hash, icon_bin, icon_mime, description):
        with self.open_db() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute('''INSERT INTO images (hash, mime, data) VALUES (%s, %s, %s)''', (icon_hash, icon_mime, icon_bin))
                    cur.commit()
                except:
                    pass
            with conn.cursor() as cur:
                try:
                    cur.execute('''INSERT INTO imagemeta (uid, hash, description) VALUES (%s, %s, %s)''', (uid, icon_hash, description))
                    cur.commit()
                except:
                    pass

    def fetch_icon(self, icon_hash):
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT data, mime FROM images WHERE hash = %s''', (icon_hash,))
                ret = cur.fetchone()
                if ret: return (ret[0].tobytes(), ret[1])
                return (None, None)
