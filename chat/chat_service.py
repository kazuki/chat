import abc, base64, configparser, json, hashlib, hmac, datetime, binascii, os.path
import urllib.parse, re, optparse, socket

import tornado.ioloop, tornado.web, tornado.websocket, tornado.httpserver, tornado.iostream
import zmq, zmq.eventloop.ioloop, zmq.eventloop.zmqstream

from chat.persistent_service import PsycopgPersistentService

URL_RE = re.compile("(?P<url>(?:https?|ftp)://(?:[a-zA-Z0-9$-_\\.\\+\\!\\~\\*\\'\\(\\),%?/;:@&=#]+))")
UNIXTIME_ORIGIN = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
WEBSOCKET_PSK = 'websocket-auth-quickhack'.encode('utf-8')
rootdir = os.path.abspath(os.path.dirname(__file__))

class ChatServiceWebSocketHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, config, auth):
        self.config = config
        self.auth_provider = auth
        self.persistent = PsycopgPersistentService(config)
        self.authenticated_user_id = None
        self.enabled_draft76 = (config.get('websocket_draft76', 'false').lower() == 'true')

    def open(self):
        print('[ws::open]', self.request.headers)
        self.ctx = zmq.Context()
        self.sub_sock = self.ctx.socket(zmq.SUB)
        self.sub_sock.connect(self.config.get('sub_endpoint', 'tcp://127.0.0.1:60000'))
        self.sub_sock.setsockopt(zmq.SUBSCRIBE, b'chat\0')
        self.strm = zmq.eventloop.zmqstream.ZMQStream(self.sub_sock)
        self.strm.on_recv(self.on_message_from_hub)
        self.push_sock = self.ctx.socket(zmq.PUSH)
        self.push_sock.connect(self.config.get('push_endpoint', 'tcp://127.0.0.1:60001'))

    def on_message(self, message):
        req = json.loads(message)

        if not self.authenticated_user_id:
            if req['m'] == 'auth':
                user_id = req['user-id']
                if not WebSocketAuth.verify_token(user_id, req['nonce'], self.request, req['token']):
                    raise tornado.web.HTTPError(401)
                self.authenticated_user_id = user_id
            return

        if req['m'] == 'post':
            dt = datetime.datetime.now(datetime.timezone.utc)
            req['d'] = int((dt - UNIXTIME_ORIGIN).total_seconds() * 1000)
            icon_hash = None
            if 'g' in req and req['g']: icon_hash = binascii.a2b_hex(req['g'].encode('ascii'))
            print(req)
            msg_hash = self.compute_message_hash(req)
            # TODO: ハッシュ値を使った重複チェック
            uid = self.persistent.store(self.current_user, dt, req['n'], req['c'], icon_hash, req['t'])
            self.push_sock.send(b'chat\0' + json.dumps({
                'n': req['n'], 'c': req['c'], 't': req['t'],
                'i': uid, 'd': req['d'], 'g': req['g']
            }).encode('utf-8'))
            self.write_message(json.dumps({
                'e': req['e'],
                'r': 'ok'
            }))
        elif req['m'] == 'latest':
            if 'i' not in req: req['i'] = -1
            self.write_message(json.dumps({
                'e': req['e'],
                'r': 'ok',
                'm': self.persistent.fetch_latest(req['c'], req['i'])
            }))
        elif req['m'] == 'store-icon':
            icon_binary = binascii.a2b_base64(req['d'].encode('ascii'))
            icon_hash = hashlib.sha1(icon_binary).digest()
            icon_hash_hex = binascii.b2a_hex(icon_hash).decode('ascii')
            self.persistent.store_icon(self.current_user, icon_hash, icon_binary, req['t'], '')
            self.write_message(json.dumps({
                'e': req['e'],
                'r': 'ok',
                'h': icon_hash_hex
            }))
        elif req['m'] == 'ping':
            self.write_message(json.dumps({
                'e': req['e'],
                'r': 'ok'
            }))
        else:
            print('unknown:', req)

    def on_message_from_hub(self, messages):
        if not self.authenticated_user_id: return
        for msg in messages:
            obj = json.loads(msg[5:].decode('utf-8'))
            self.write_message(json.dumps({
                'm': 'strm',
                'd': obj
            }))

    def on_close(self):
        print('[ws::close]')
        self.strm.close()
        self.sub_sock.close()
        self.push_sock.close()

    def compute_message_hash(self, obj):
        txt = self.current_user + "\0" + obj['r'] + "\0" + obj['n'] + "\0" + obj['c'] + "\0" + obj['t'];
        sha1 = hashlib.sha1()
        sha1.update(txt.encode('utf-8'))
        return sha1.digest()

    def get_current_user(self):
        # TODO: ChromiumがWebSocketのBasic認証に対応したら指定されたauth_providerを利用する
        if not self.authenticated_user_id:
            raise tornado.web.HTTPError(401)
        return self.authenticated_user_id

    def allow_draft76(self):
        return self.enabled_draft76

class ChatServiceLiteHandler(tornado.web.RequestHandler):
    def initialize(self, config, auth):
        self.config = config
        self.auth_provider = auth
        self.persistent = PsycopgPersistentService(config)
        self.loader = tornado.template.Loader(os.path.join(rootdir, 'templates'))
        self.ctx = zmq.Context()
        self.push_sock = self.ctx.socket(zmq.PUSH)
        self.push_sock.connect(self.config.get('push_endpoint', 'tcp://127.0.0.1:60001'))

    def generate_(self, name = None, color = None, count = None):
        if name is None:
            name = urllib.parse.unquote(self.get_cookie('lite_chat_username', urllib.parse.quote('名無し')))
        if color is None:
            color = urllib.parse.unquote(self.get_cookie('lite_chat_color', urllib.parse.quote('black')));
        if count is None:
            try:
                count = int(self.get_cookie('lite_chat_count', '20'));
            except: pass
        messages = self.persistent.fetch_latest(count, None)
        for i in range(len(messages)):
            messages[i]['d'] = datetime.datetime.fromtimestamp(messages[i]['d'] / 1000).strftime('%m/%d %H:%M:%S')
            items = URL_RE.split(messages[i]['t'])
            for x in range(len(items)):
                if x % 2 == 0:
                    items[x] = (items[x], None)
                else:
                    items[x] = (urllib.parse.unquote_plus(items[x]), items[x])
            messages[i]['t'] = items
        self.finish(self.loader.load('lite.html').generate(messages = messages, name = name, color = color, count = str(count)))

    def get(self):
        self.generate_()

    def post(self):
        name = self.get_argument('name', '名無し')
        body = self.get_argument('body', None)
        color = self.get_argument('color', 'black')
        count = 20
        try:
            count = int(self.get_argument('count', '20'))
        except: pass

        self.set_cookie('lite_chat_username', urllib.parse.quote(name))
        self.set_cookie('lite_chat_color', urllib.parse.quote(color))
        self.set_cookie('lite_chat_count', str(count))

        if body is not None and len(body) > 0:
            dt = datetime.datetime.now(datetime.timezone.utc)
            msgid = self.persistent.store(self.current_user, dt, name, color, None, body)
            self.push_sock.send(b'chat\0' + json.dumps({
                'n': name, 'c': color, 't': body,
                'i': msgid, 'd': int((dt - UNIXTIME_ORIGIN).total_seconds() * 1000), 'g': None
            }).encode('utf-8'))
        self.redirect(urllib.parse.urlparse(self.request.headers.get('Referer', self.request.path)).path)

    def get_current_user(self):
        return self.auth_provider.get_user_id(self.request)

class HashedImageHandler(tornado.web.RequestHandler):
    def initialize(self, config, auth):
        self.config = config
        self.auth_provider = auth
        self.persistent = PsycopgPersistentService(config)
        self.mc_strm = None
        self.cache_key = None
        self.original_image = None
        self.max_size = None

    @tornado.web.asynchronous
    def get(self, image_hash):
        binary, mime_type = self.persistent.fetch_icon(binascii.a2b_hex(image_hash.encode('ascii')))
        if not binary: raise tornado.web.HTTPError(404)
        if self.get_argument('s', None):
            max_size = int(self.get_argument('s'))
            self.set_header("Content-Type", 'image/jpeg')
            self.cache_key = image_hash + '-' + str(max_size)
            self.original_image = binary
            self.max_size = max_size
            self.mc_strm = tornado.iostream.IOStream(socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0))
            self.mc_strm.connect(('127.0.0.1', 11211), self._mc_connected)
            return
        self.set_header("Content-Type", mime_type)
        self.write(binary)
        self.finish()

    def _mc_connected(self):
        self.mc_strm.write(('get ' + self.cache_key + '\r\n').encode('ascii'))
        self.mc_strm.read_until(b'\r\n', self._mc_read_header)
    def _mc_read_header(self, header):
        if len(header) == 5 and header[0:3] == b'END':
            self._convert_process(self.original_image, self.max_size)
        elif len(header) > 6 and header[0:6] == b'VALUE ':
            header = header[6 + len(self.cache_key) + 1:]
            header = header[header.index(b' ')+1:]
            body_size = int(header[:len(header)-2].decode('ascii'))
            self.mc_strm.read_bytes(body_size, self._mc_read_body)
        else:
            raise tornado.web.HTTPError(500)
    def _mc_read_body(self, body):
        self.write(body)
        self.finish()
        self.mc_strm.close()
    def _convert_process(self, src_blob, size):
        args = ['convert', '-resize', str(size) + 'x' + str(size), '-quality', '95', '-', 'jpeg:-']
        STREAM = tornado.process.Subprocess.STREAM
        sub_process = tornado.process.Subprocess(
            args, stdin=STREAM, stdout=STREAM, stderr=STREAM
        )
        sub_process.stdin.write(src_blob)
        sub_process.stdin.close()
        sub_process.stdout.read_until_close(self._on_convert_finished)

    def _on_convert_finished(self, blob):
        self.mc_strm.write(('set ' + self.cache_key + ' 0 0 ' + str(len(blob)) + '\r\n').encode('ascii'))
        self.mc_strm.write(blob)
        self.mc_strm.write(b'\r\n')
        self.write(blob)
        self.mc_strm.read_until(b'\r\n', self._mc_read_set_response)
    def _mc_read_set_response(self, response):
        print(response)
        self.finish()
        self.mc_strm.close()

class AuthProvider(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def get_user_id(self, req): pass

class BasicAuthProvider(AuthProvider):
    def get_user_id(self, req):
        if 'Authorization' in req.headers:
            basic_auth = req.headers['Authorization']
            if basic_auth[0:5] == 'Basic':
                basic_auth = base64.b64decode(basic_auth[6:].encode('ascii')).decode('utf-8')
                if ':' in basic_auth:
                    return basic_auth[0:basic_auth.index(':')]
        raise tornado.web.HTTPError(401)

class WebSocketAuth(object):
    def create_token(userid, nonce, req):
        h = hmac.new(WEBSOCKET_PSK, digestmod = hashlib.sha256)
        h.update(userid.encode('utf-8'))
        h.update(binascii.a2b_base64(nonce.encode('ascii')))
        return binascii.b2a_base64(h.digest()).decode('ascii').strip()

    def verify_token(userid, nonce, req, token):
        token2 = WebSocketAuth.create_token(userid, nonce, req)
        if token != token2:
            print('verify-token failed:', token, '=', token2)
        return token == token2

class WebSocketAuthTokenGenerator(tornado.web.RequestHandler):
    def initialize(self, auth):
        self.auth_provider = auth

    def get(self):
        userid = self.auth_provider.get_user_id(self.request)
        nonce = binascii.b2a_base64(os.urandom(48)).decode('ascii').strip()
        token = WebSocketAuth.create_token(userid, nonce, self.request)
        self.write('WebSocketAuthUserID = \"' + userid + '\";\r\n')
        self.write('WebSocketAuthNonce = \"' + nonce + '\";\r\n')
        self.write('WebSocketAuthToken = \"' + token + '\";')

class DefaultStaticHtmlHandler(tornado.web.RequestHandler):
    def get(self):
        path = os.path.join(rootdir, 'static/chat.html')
        self.set_header('Content-Type', 'text/html')
        self.set_header('Content-Length', str(os.path.getsize(path)))
        with open(path, mode='rb') as fd:
            self.write(fd.read())

class ChatService(object):
    def __init__(self, config_path = None):
        config = configparser.ConfigParser()
        if config_path: config.read(config_path)
        self.chat_config = config['DEFAULT']
        if 'chat_service' in config: self.chat_config = config['chat_service']

    def run(self):
        auth_provider = BasicAuthProvider()
        app = tornado.web.Application([
            (r'/ws', ChatServiceWebSocketHandler, dict(config=self.chat_config, auth = auth_provider)),
            (r'/hash/([a-f0-9]{40})', HashedImageHandler, dict(config=self.chat_config, auth = auth_provider)),
            (r'/lite', ChatServiceLiteHandler, dict(config=self.chat_config, auth = auth_provider)),
            (r'/token.js', WebSocketAuthTokenGenerator, dict( auth = auth_provider)),
            (r"/", DefaultStaticHtmlHandler),
            (r"/(.*)", tornado.web.StaticFileHandler, {"path": os.path.join(rootdir, "static")})
        ])
        sockets = tornado.netutil.bind_sockets(self.chat_config.get('port', 8888))
        if self.chat_config.get('fork', 'False') == 'True':
            tornado.process.fork_processes(0)
        zmq.eventloop.ioloop.install()
        http_server = tornado.httpserver.HTTPServer(app)
        http_server.add_sockets(sockets)
        tornado.ioloop.IOLoop.instance().start()

def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--config', dest='config_path',
                      help='configuration file path')
    options, args = parser.parse_args()
    app = ChatService(config_path = options.config_path)
    app.run()

if __name__ == '__main__':
    main()
