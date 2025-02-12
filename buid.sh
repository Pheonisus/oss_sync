pip install -r ./requirements.txt
pip install pyinstaller
pyinstaller --onefile oss_sync.py --noconsole --distpath .
pyinstaller --onefile oss_sync_service.py --noconsole --distpath .