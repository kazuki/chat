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

    # 受信する通知情報を取得 (戻り値はstore_subscriptionsのinfoと同じ形式)
    @abc.abstractmethod
    def fetch_subscriptions(self, uid): pass

    # 受信する通知を登録 info = {'facility': level, ...}
    @abc.abstractmethod
    def store_subscriptions(self, uid, info): pass

    # 通知を永続化ストレージに配信(戻り値は通知情報のユニークID)
    @abc.abstractmethod
    def store_notification(self, facility, level, body, date): pass

    # 未読通知を取得
    @abc.abstractmethod
    def fetch_notifications(self, uid): pass

    # 通知を既読にする
    @abc.abstractmethod
    def set_read_notifications(self, uid, nids): pass

class PsycopgPersistentService(PersistentServiceBase):
    def __init__(self, config):
        self.db_name = config.get('db_name', None)
        self.db_user = config.get('db_user', None)
        self.db_pass = config.get('db_pass', None)
        self.db_host = config.get('db_host', 'localhost')

    def open_db(self):
        return psycopg2.connect(database=self.db_name, user=self.db_user, password=self.db_pass, host=self.db_host)

    def _db_result_to_unixtime(self, dt):
        if dt.tzinfo: dt = dt.astimezone(datetime.timezone.utc)
        return int((dt - UNIXTIME_ORIGIN).total_seconds() * 1000)

    def dbrow_to_json(self, row):
        icon_hash = None
        if row[4]: icon_hash = binascii.b2a_hex(row[4]).decode('ascii')
        return {'i': row[0], 'd': self._db_result_to_unixtime(row[1]),
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

    def fetch_subscriptions(self, uid):
        ret = {}
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT facility,level FROM subscriptions WHERE uid = %s''', (uid,))
                ret = dict([(f,l) for f,l in cur.fetchall()])
        return ret

    def store_subscriptions(self, uid, info):
        insert_values = []
        for k,v in info.items():
            insert_values.append({'uid':uid, 'facility': k, 'level': v})
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''DELETE FROM subscriptions WHERE uid = %s''', (uid,))
                if len(insert_values) > 0:
                    cur.executemany('''INSERT INTO subscriptions(uid, facility, level) VALUES(%(uid)s, %(facility)s, %(level)s)''', insert_values)

    def store_notification(self, facility, level, body, date):
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('INSERT INTO notifications (date, facility, level, body) VALUES (%s, %s, %s, %s) RETURNING id',
                            (date, facility, level, body))
                conn.commit()
                nid = cur.fetchone()[0]
                cur.execute('''insert into notification_box(uid,read,nid) ''' +
                            '''select uid,False,%(nid)s from subscriptions where facility = %(facility)s and level >= %(level)s''',
                            {'nid':nid, 'facility': facility, 'level': level})
                return nid

    def fetch_notifications(self, uid):
        with self.open_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''select id,facility,level,date,body from (select * from notification_box where uid=%s and read=False) as t,notifications where t.nid = notifications.id''', (uid,))
                return [{'i':x[0], 'f':x[1], 'l':x[2], 'd':self._db_result_to_unixtime(x[3]), 't':x[4]} for x in cur.fetchall()]

    def set_read_notifications(self, uid, nids):
        if len(nids) == 0: return
        with self.open_db() as conn:
            with conn.cursor() as cur:
                for nid in nids:
                    cur.execute('UPDATE notification_box SET read = True WHERE uid=%s and nid=%s', (uid, nid))
