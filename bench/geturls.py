import sys
import re

for match in re.finditer('<a\s+href="(.+?)"', sys.stdin.read()):
    print match.group(1)
