import os
import sys
import time


def test_requests():
    import requests
    session = requests.Session()
    def iter():
        resp = session.get('http://127.0.0.1:8000/')
        return resp.content

    return iter


def test_httplib():
    import httplib
    cn = httplib.HTTPConnection('127.0.0.1', 8000)
    cn.connect()
    def iter():
        cn.request('GET', '/', headers={'Connection': 'keep-alive'})
        resp = cn.getresponse(True)
        body = resp.read()
        resp.close()
        return body

    return iter


def test_hlupik():
    import hlupik
    https, host, port, hn, _ = hlupik.split_url('http://127.0.0.1:8000')
    cn = hlupik.Connection.make(host, port, https, timeout=None)
    client = hlupik.Client()
    def iter():
        resp = client.request(cn, 'GET', '/', headers={'Connection': 'keep-alive',
                                                       'Host': hn,
                                                       'Accept-Encoding': 'identity'}.items())
        return str(resp.body)

    return iter


def test_hlupik_pool():
    import hlupik
    pool = hlupik.Pool(timeout=None)
    def iter():
        resp = pool.request('GET', 'http://127.0.0.1:8000/', headers={'Connection': 'keep-alive'})
        return str(resp.body)

    return iter


def test_raw():
    import socket
    socket = socket.create_connection(('127.0.0.1', 8000))
    def iter():
        request = ('GET / HTTP/1.1\r\n'
                   'Connection: keep-alive\r\n'
                   '\r\n')

        socket.send(request)
        data = socket.recv(4096)
        headers_end = data.find('\r\n\r\n')
        body = data[headers_end+4:]
        return body

    return iter


def timeit(iteration):
    from resource import getrusage, RUSAGE_SELF
    start = getrusage(RUSAGE_SELF)[0]
    for _ in xrange(10000):
        body = iteration()
        assert len(body) == 1000
    end = getrusage(RUSAGE_SELF)[0]
    print end - start


def profile(iteration):
    import cProfile
    p = cProfile.Profile(time.clock)
    try:
        p.runcall(timeit, iteration)
    finally:
        p.dump_stats('/tmp/output.prof')


it = globals()['test_{}'.format(sys.argv[1])]()
if 'PROFILE' in os.environ:
    profile(it)
else:
    timeit(it)
