#!/usr/bin/python3
import zmq, configparser, optparse, sys

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
    parser.add_option('-t', '--type', dest='type',
                      help='message type (c or n or m)')
    parser.add_option('-u', '--user', dest='user',
                      help='user-id (type=m only)')
    parser.add_option('-b', '--body', dest='body',
                      help='message body')
    parser.add_option('-f', '--facility', dest='facility',
                      help='facility (type=n only)')
    parser.add_option('-l', '--level', dest='level',
                      help='log level (type=n only. alert or warning or info)')
    options, args = parser.parse_args()

    config_file = configparser.ConfigParser()
    if options.config_path: config_file.read(options.config_path)
    config = config_file['DEFAULT']

    LOG_LEVELS = ('alert', 'warning', 'info')
    if options.type not in ('c', 'n', 'm'):
        print('unknown type')
        return
    if options.body is None:
        print('body is required')
        return
    if options.type == 'n':
        if options.facility is None or options.level is None:
            print('facility and level is required')
            return
        if options.level not in LOG_LEVELS:
            print('unknown log-level')
            return
        options.level = LOG_LEVELS.index(options.level)
    if options.type == 'm':
        if options.user is None:
            print('user-id is required')
            return
    if options.body == '-':
        options.body = sys.stdin.read()

    msg_body = None
    if options.type == 'c':
        msg_body = b'c' + options.body.encode('utf-8')
    elif options.type == 'n':
        msg_body = b'n' + options.facility.encode('utf-8') + b'\0' + bytes((options.level,)) + options.body.encode('utf-8')
    elif options.type == 'm':
        msg_body = b'm' + options.user.encode('utf-8') + b'\0' + options.body.encode('utf-8')

    ctx = zmq.Context()
    push_sock = ctx.socket(zmq.PUSH)
    push_sock.connect(config.get('push_endpoint', 'tcp://127.0.0.1:60001'))
    push_sock.send(msg_body)

if __name__ == '__main__':
    main()
