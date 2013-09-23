import configparser, datetime, json
from chat.persistent_service import PsycopgPersistentService

UNIXTIME_ORIGIN = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

class NotificationPersistentFilter(object):
    def __init__(self, config_path):
        config = configparser.ConfigParser()
        if config_path: config.read(config_path)
        defcfg = config['DEFAULT']
        if 'chat_service' in config: defcfg = config['chat_service']
        self.persistent = PsycopgPersistentService(defcfg)

    def _parse_msg(self, m):
        if m[0] == b'n'[0]:
            idx = m.find(b'\0')
            if idx < 0: return None
            return ('n', m[1:idx].decode('utf-8'), m[idx + 1], m[idx + 2:].decode('utf-8'))
        return None

    def __call__(self, msg):
        parsed = self._parse_msg(msg)
        if parsed is not None:
            dt = datetime.datetime.now(datetime.timezone.utc)
            if parsed[0] == 'n':
                nid = self.persistent.store_notification(parsed[1], parsed[2], parsed[3], dt)
                msg = b'n' + parsed[1].encode('utf-8') + bytes((0,parsed[2])) + json.dumps({
                    'i': nid, 'f': parsed[1], 'l': parsed[2],
                    'd': int((dt - UNIXTIME_ORIGIN).total_seconds() * 1000), 't': parsed[3]
                }).encode('utf-8')
        return msg
