import zmq, configparser, optparse

class MessageHub(object):
    def __init__(self, config_path = None):
        config = configparser.ConfigParser()
        if config_path: config.read(config_path)
        defcfg = config['DEFAULT']
        if 'chat_service' in config: defcfg = config['chat_service']
        self.ctx = zmq.Context()
        self.pub_sock = self.ctx.socket(zmq.PUB)
        self.pub_sock.bind(defcfg.get('pub_endpoint', 'tcp://*:60000'))
        self.pull_sock = self.ctx.socket(zmq.PULL)
        self.pull_sock.bind(defcfg.get('pull_endpoint', 'tcp://*:60001'))

    def run(self):
        while True:
            msg = self.pull_sock.recv()
            print(msg)
            self.pub_sock.send(msg)

def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--config', dest='config_path',
                      help='configuration file path')
    options, args = parser.parse_args()
    app = MessageHub(config_path = options.config_path)
    app.run()

if __name__ == '__main__':
    main()
