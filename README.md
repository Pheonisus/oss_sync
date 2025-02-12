# OSS Sync Oss同步


## 两种上传模式
- trigger 一次性同步 （未实现）
- continue 持续同步，类似于服务
## 参数说明
- start 持续同步服务启动
- stop 持续同步服务关闭
- restart 持续同步服务重启/重新加载配置
- status 持续同步服务状态查询
- trigger 一次性同步（未实现）
	
## 后台同步配置
通过配置文件设置同步目录，可同时配置和监控多个目录。
配置文件：```./config.json```
配置文件格式(可配置多个同步目录和账号)：
```
[{
        "access_key_id": "{aliyun获取}",
        "access_key_secret": "{aliyun获取}",
        "endpoint": "oss-cn-shenzhen.aliyuncs.com{aliyun内部资源使用需加internal}",
        "bucket_name": "{aliyun获取}",
        "local_path": "/Users/pheonisus/test/",
        "oss_path": "test/",
        "direction": "local2oss",
        "exclude": [
            ".git/",
            ".DS_Store"
        ]
    }
]
```
## 一次性同步命令 TODO
```
```

## 同步服务启动命令
```oss_sync_service start```