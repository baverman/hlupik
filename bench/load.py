import os
import time

content = b'#' * int(os.environ.get('SIZE', 1024))


def application(env, start_response):
    start_response('200 OK', [('Content-Type','text/plain'),
                              ('Connection', 'keep-alive'),
                              ('Content-Length', str(len(content)))])
    return [content]
