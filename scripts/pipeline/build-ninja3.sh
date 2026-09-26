#!/system/bin/sh
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd /data/data/com.termux/files/usr/tmp/ninja-1.12.1
exec python3 configure.py --bootstrap
