import pytest
from hlupik import Client, split_url, BadStatusLine, TruncatedContent


def gen_headers(status, headers):
    response = ['HTTP/1.1 {}\r\n'.format(status)]
    for k, v in headers.items():
        response.append('{}: {}\r\n'.format(k, v))

    return ''.join(response)


def chunks(body, chunk_size):
    result = []
    while body:
        result.append(body[:chunk_size])
        body = body[chunk_size:]

    return result


def sr(body='', headers=None, status='200 OK', content_length=True):
    headers = headers or {}
    if content_length:
        headers['Content-Length'] = len(body)
    return '{}\r\n{}'.format(gen_headers(status, headers), body)


def cr(body, chunk_size, headers=None, status='200 OK'):
    headers = headers or {}
    headers['Transfer-Encoding'] = 'chunked'
    header = gen_headers(status, headers)
    result = []
    while body:
        chunk = body[:chunk_size]
        body = body[chunk_size:]
        result.append('{}\r\n{}\r\n'.format(hex(len(chunk))[2:], chunk))

    return header + '\r\n' + ''.join(result) + '0\r\n\r\n'


class Connection(object):
    def __init__(self, *responses):
        self.responses = list(responses)

    def recv_into(self, buf, size):
        data = self.responses.pop(0)
        data_len = len(data)
        rsize = min(data_len, size)
        buf[:rsize] = data[:rsize]
        if data[rsize:]:
            self.responses.insert(0, data[rsize:])
        return rsize

    def sendall(self, data):
        pass


def test_simple():
    cl = Client()
    cn = Connection(sr('boo'))
    resp = cl.request(cn, 'GET', '/', [('Header', 'value')])
    assert resp.body == 'boo'
    assert not cn.responses


def test_chunked_encoding():
    cl = Client()
    content = ''.join(map(str, xrange(10)))
    cn = Connection(cr(content, 1000))
    resp = cl.request(cn, 'GET', '/')
    assert resp.body == content
    assert not cn.responses


def test_chunked_with_multiple_response():
    cl = Client()
    content = ''.join(map(str, xrange(100)))
    cn = Connection(*chunks(cr(content, 50), 30))
    resp = cl.request(cn, 'GET', '/')
    assert resp.body == content
    assert not cn.responses


def test_split_url():
    split_url('http://boo.loc:8000/booo') == ('boo.loc', 8000, False, 'boo.loc:8000', '/booo')
    split_url('http://boo.loc/booo') == ('boo.loc', 80, False, 'boo.loc', '/booo')
    split_url('https://boo.loc/booo') == ('boo.loc', 443, True, 'boo.loc', '/booo')


def test_bad_status_line():
    cl = Client()
    cn = Connection('')
    with pytest.raises(BadStatusLine):
        resp = cl.request(cn, 'GET', '/')
    assert not cn.responses


def test_multiple_header_chunks():
    cl = Client()
    content = ''.join(map(str, xrange(100)))
    cn = Connection(*chunks(sr(content), 5))
    resp = cl.request(cn, 'GET', '/')
    assert resp.body == content
    assert resp.header_data == 'HTTP/1.1 200 OK\r\nContent-Length: 190\r\n'
    assert not cn.responses


def test_truncated_content():
    cl = Client()
    content = ''.join(map(str, xrange(100)))
    cn = Connection(*(chunks(sr(content)[:-10], 50) + ['']))
    try:
        resp = cl.request(cn, 'GET', '/')
        assert False, 'TruncatedContent must be raised'
    except TruncatedContent as e:
        pass

    assert e.body == content[:-10]
    assert not cn.responses


def test_response_without_content_length():
    cl = Client()
    content = ''.join(map(str, xrange(100)))
    cn = Connection(*(chunks(sr(content, content_length=False), 50) + ['']))
    resp = cl.request(cn, 'GET', '/')
    assert resp.body == content
    assert not cn.responses


def test_large_body():
    cl = Client(recv_size=11, body_chunk_size=50)
    content = ''.join(map(str, xrange(100)))
    cn = Connection(*(chunks(sr(content, content_length=False), 50) + ['']))
    resp = cl.request(cn, 'GET', '/')
    assert resp.body == content
    assert not cn.responses


def test_large_body_for_chunked_response():
    cl = Client(recv_size=11, body_chunk_size=50)
    content = ''.join(map(str, xrange(100)))
    cn = Connection(*(chunks(cr(content, 10), 50)))
    resp = cl.request(cn, 'GET', '/')
    assert resp.body == content
    assert not cn.responses


def test_trancated_content_while_reading_chunk_body():
    cl = Client()
    content = ''.join(map(str, xrange(20)))
    cn = Connection(*(chunks(cr(content, 5)[:-8], 10) + ['']))
    try:
        resp = cl.request(cn, 'GET', '/')
        assert False, 'TruncatedContent must be raised'
    except TruncatedContent as e:
        pass
    assert e.body == content[:-1]
    assert not cn.responses


def test_trancated_content_while_reading_chunk_header():
    cl = Client()
    content = ''.join(map(str, xrange(20)))
    response = cr(content, 5)
    cn = Connection(*[response[:67], ''])
    try:
        resp = cl.request(cn, 'GET', '/')
        assert False, 'TruncatedContent must be raised'
    except TruncatedContent as e:
        pass
    assert e.body == content[:10]
    assert not cn.responses
