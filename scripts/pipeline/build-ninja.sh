#!/system/bin/sh
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd /data/data/com.termux/files/usr/tmp/ninja-1.12.1
python3 configure.py --bootstrap
