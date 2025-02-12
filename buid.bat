pip install -r ./requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
pip install pyinstaller -i https://mirrors.aliyun.com/pypi/simple/
pyinstaller --onefile oss_sync.py --noconsole --distpath .
pyinstaller --onefile oss_sync_service.py --distpath .