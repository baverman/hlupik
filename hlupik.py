import re
import ssl
import socket
import time

from errno import EAGAIN
from urlparse import urlsplit
from contextlib import contextmanager
from collections import deque


class BadStatusLine(Exception):
    pass


class TruncatedContent(Exception):
    def __init__(self, header_data, body):
        Exception.__init__(self, 'Truncated content')
        self.header_data = header_data
        self.body = body


class Response(object):
    def __init__(self, header_data, body):
        self.header_data = header_data
        self.body = body


header_re = re.compile('(?im)^(content-length|connection|transfer-encoding): (.+?)\r')
HEADER_SEP = '\r\n\r\n'


def parse_headers(data):
    return {str(name).lower(): str(value)
            for name, value in header_re.findall(data)}


def set_recv_buf(sock, size):  # pragma: no cover
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)


def split_url(url):
    parts = urlsplit(url)
    https = parts.scheme == 'https'
    host, _, port = parts.netloc.partition(':')
    if not port:
        port = 443 if https else 80
    else:
        port = int(port)

    return https, host, port, parts.netloc, parts.path + '?' + parts.query


class Connection(object):  # pragma: no cover
    def __init__(self, socket, unwrap=True):
        self.socket = socket
        if unwrap:
            self.sendall = socket._sock.sendall
            self.recv_into = socket._sock.recv_into
        else:
            self.sendall = socket.sendall
            self.recv_into = socket.recv_into

        self.closed = False

    @classmethod
    def make(self, host, port, https=False, bufsize=16384, timeout=10):
        sock = socket.create_connection((host, port), timeout=timeout)
        set_recv_buf(sock, bufsize)
        if https:
            context = ssl._create_default_https_context()
            sock = context.wrap_socket(sock, server_hostname=host)
        return Connection(sock, not https)


class Pool(object):
    def __init__(self, timeout=10):
        self.timeout = timeout
        self._connections = {}
        self._clients = deque()

    @contextmanager
    def conn(self, host, port, https):
        key = (host, port, https)
        cn = self.get_conn(key)
        try:
            cl = self._clients.pop()
        except IndexError:
            cl = Client()

        try:
            yield cn, cl
        finally:
            self._clients.append(cl)
            if not cn.closed:
                self.put_conn(key, cn)

    def queue(self, key):
        try:
            return self._connections[key]
        except KeyError:
            pass

        result = self._connections[key] = deque()
        return result

    def get_conn(self, key):
        q = self.queue(key)
        try:
            return q.pop()
        except IndexError:
            return Connection.make(key[0], key[1], key[2], timeout=self.timeout)

    def put_conn(self, key, cn):
        self.queue(key).append(cn)

    def request(self, method, url, headers=None, hostname=None):
        https, host, port, hn, path = split_url(url)
        headers = headers or {}
        with self.conn(host, port, https) as (cn, cl):
            headers['Host'] = hostname or hn
            return cl.request(cn, method, path, headers.items())


class Client(object):
    def __init__(self, recv_size=16384, header_size=65536, body_chunk_size=2**20):
        assert body_chunk_size - recv_size > 0
        self.recv_size = recv_size
        self.max_header_size = header_size
        self.body_chunk_size = body_chunk_size
        self.header_buf = bytearray(header_size + recv_size)
        self.body_buf = bytearray(body_chunk_size)

    def request(self, conn, method, url, headers=None):
        request = []
        ex = request.extend
        ex((method, ' ', url, ' HTTP/1.1\r\n'))
        for k, v in headers or []:
            ex((k, ': ', v, '\r\n'))
        ex(('\r\n',))
        conn.sendall(''.join(request))

        rsize = self.recv_size
        header_size = 0
        header_mv = memoryview(self.header_buf)
        body_size = 0
        body_mv = memoryview(self.body_buf)
        body_data = None
        partial = False
        while True:
            try:
                size = conn.recv_into(header_mv[header_size:], rsize)
            except IOError as e:
                if e.errno == EAGAIN:
                    time.sleep(0.01)
                    continue

            if not size:
                raise BadStatusLine('Bad status line: "{}"'.format(self.header_buf[:header_size]))
            header_end = self.header_buf.find(HEADER_SEP, max(0, header_size-4), header_size + size)
            header_size += size
            if header_end >= 0:
                body_size = header_size - header_end - 4
                body_mv[:body_size] = header_mv[header_end+4:header_size]
                header_end += 2
                break

            assert header_size <= self.max_header_size

        header_data = self.header_buf[:header_end]
        headers = parse_headers(header_data)
        if 'content-length' in headers:
            need_to_read = int(headers['content-length']) - body_size
            assert need_to_read >= 0
        elif headers.get('transfer-encoding', None) == 'chunked':
            need_to_read = -2
        else:
            need_to_read = -1

        if need_to_read == 0:
            body_data = self.body_buf[:body_size]
        elif need_to_read == -2:
            body_data, partial = self.read_chunked(conn, body_size)
        else:
            while True:
                size = conn.recv_into(body_mv[body_size:], rsize)

                if not size:
                    if need_to_read > 0:
                        partial = True
                    break

                body_size += size
                if need_to_read > 0:
                    need_to_read -= size
                    if not need_to_read:
                        break
                    assert need_to_read > 0

                if body_size > self.body_chunk_size - rsize:
                    if body_data is None:
                        body_data = bytearray()
                    body_data.extend(self.body_buf[:body_size])
                    body_size = 0

            if body_data is None:
                body_data = self.body_buf[:body_size]
            else:
                body_data.extend(self.body_buf[:body_size])

        if partial:
            conn.closed = True
            raise TruncatedContent(header_data, body_data)
        else:
            return Response(header_data, body_data)

    def read_chunked(self, conn, end):
        start = 0
        body_data = bytearray()
        buf = self.body_buf
        mv = memoryview(buf)
        rsize = self.recv_size
        max_body_size = self.body_chunk_size - rsize
        while True:
            while True:
                if end - start:
                    chunk_size_end = buf.find('\r\n', start, end)
                else:
                    chunk_size_end = -1

                if chunk_size_end > 0:
                    break
                size = conn.recv_into(mv[end:], rsize)
                if not size:
                    return body_data, True
                end += size

            ext_pos = buf.find(';', start, chunk_size_end)
            if ext_pos < 0:
                ext_pos = chunk_size_end

            chunk_size_end += 2
            chunk_size = int(str(buf[start:ext_pos]), 16)
            available_data = end - chunk_size_end
            need_to_read = chunk_size + 2 - available_data
            if need_to_read <= 0:
                if not chunk_size:
                    break
                body_data.extend(buf[chunk_size_end:chunk_size_end + chunk_size])
                start = chunk_size_end + chunk_size + 2
            else:
                while True:
                    if end > max_body_size:
                        body_data.extend(buf[chunk_size_end:end])
                        chunk_size_end = end = 0

                    size = conn.recv_into(mv[end:], rsize)
                    if not size:
                        body_data.extend(buf[chunk_size_end:end])
                        return body_data, True

                    end += size
                    if need_to_read > size:
                        need_to_read -= size
                    else:
                        start = end - (size - need_to_read)
                        body_data.extend(buf[chunk_size_end:start-2])
                        if end > max_body_size:
                            mv[:end-start] = mv[start:end]
                            start, end = 0, end - start
                        break
        return body_data, False
