# 作用

全自动守护exporter采集实例，包括：

1. 根据指定的监控模型ObjectId获取实例信息，并自动根据规则创建exporter启动配置，存放至每个实例的exporter字段
2. 根据exporter字段的配置，启动新的exporter实例，同时也会判断机器当前存在的exporter进程是否需要kill，保证启动的exporter进程与CMDB的实例一一对应


# 使用方式

1. 将该项目作为子模块的形式引入到各采集插件包
2. 采集插件包的`deploy/start_script.sh`写成类似：

```shell
#!/bin/bash
../exporter-supervisor.py KAFKA_SERVICE_NODE ./conf/conf.default.yaml

```

3. 插件包需要有个`conf/conf.default.yaml`配置，里面必须有如下配置：
```yaml
# exporter进程的keyword，支持"java|xxx|xx"的正则，程序会根据egrep的方式去过滤
exporter_keyword: "kafka_exporter"

# exporter启动的端口范围
port_range: [32000, 32999]

# exporter的启动脚本模板，{xx}的变量将被替换
start_cmd_template: "bash ./bin/start.sh --kafka-server {ip}:{port} --exporter-port {exporter_port}"


```