import zmq, configparser, optparse, datetime
from chat.persistent_service import PsycopgPersistentService

class NotificationPersistentService(object):
    def __init__(self, config_path = None):
        config = configparser.ConfigParser()
        if config_path: config.read(config_path)
        defcfg = config['DEFAULT']
        if 'chat_service' in config: defcfg = config['chat_service']
        self.ctx = zmq.Context()
        self.sub_sock = self.ctx.socket(zmq.SUB)
        self.sub_sock.connect(defcfg.get('sub_endpoint', 'tcp://127.0.0.1:60000'))
        self.sub_sock.setsockopt(zmq.SUBSCRIBE, b'')
        self.persistent = PsycopgPersistentService(defcfg)

    def run(self):
        def parse_msg(m):
            print(m)
            if m[0] == b'n'[0]:
                idx = m.find(b'\0')
                if idx < 0: return None
                return ('n', m[1:idx].decode('utf-8'), m[idx + 1], m[idx + 2:].decode('utf-8'))
            return None

        while True:
            msg = parse_msg(self.sub_sock.recv())
            if msg is None: continue
            print(msg)
            if msg[0] == 'n':
                self.persistent.store_notification(msg[1], msg[2], msg[3], datetime.datetime.now(datetime.timezone.utc))

def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--config', dest='config_path',
                      help='configuration file path')
    options, args = parser.parse_args()
    app = NotificationPersistentService(config_path = options.config_path)
    app.run()

if __name__ == '__main__':
    main()
