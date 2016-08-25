# from gevent import monkey; monkey.patch_all()
# import gevent.pool
from cStringIO import StringIO
import zlib

import sys
import time
import logging
import hashlib
# logging.basicConfig(level='DEBUG')

import hlupik
import requests

result = []
pool = hlupik.Pool(timeout=10)
# gpool = gevent.pool.Pool(10)
session = requests.Session()

def fetch_hlupik(url):
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    url = url.strip()
    resp = pool.request('GET', url, headers={'Connection': 'keep-alive', 'Accept-Encoding': 'gzip'})
    # resp = pool.request('GET', url, headers={'Connection': 'keep-alive'})
    body = decompressor.decompress(str(resp.body))
    print url, len(body)
    result.append((url, body))

def fetch_requests(url):
    url = url.strip()
    resp = session.get(url)
    print url, len(resp.content)
    result.append((url, resp.content))

tname = sys.argv[1]
func = globals()['fetch_' + tname]

def test():
    from resource import getrusage, RUSAGE_SELF
    start = getrusage(RUSAGE_SELF)[0]

    # list(gpool.imap_unordered(func, open('urls.txt')))
    # print 'Done'

    for r in list(open('urls.txt'))[:]:
        func(r)

    end = getrusage(RUSAGE_SELF)[0]
    print end - start

    # for url, body in result:
    #     with open('/tmp/{}/{}.html'.format(tname, url.replace('/', '-')), 'w') as f:
    #         f.write(body)

# test()


import cProfile
p = cProfile.Profile(time.clock)
p.runcall(test)
p.dump_stats('/tmp/output.prof')
# p.print_stats('tottime')
