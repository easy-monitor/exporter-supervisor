# 作用

全自动守护exporter采集实例，包括：

1. 根据指定的监控模型ObjectId获取实例信息，并自动根据规则创建exporter启动配置，存放至每个实例的exporter字段
2. 根据exporter字段的配置，启动新的exporter实例，同时也会判断机器当前存在的exporter进程是否需要kill，保证启动的exporter进程与CMDB的实例一一对应


# 使用方式
_注意，该项目不会独立执行，只作为插件包的框架文件_

1. 将该项目作为子模块的形式引入到各采集插件包的supervisor目录
2. 采集插件包（如[kafka-collector-plugin]）的`deploy/start_script.sh`调用，一般写成如下格式：

```shell
#!/bin/bash
./supervisor/exporter-supervisor.py KAFKA_SERVICE_NODE

```

3. 插件包（如[kafka-collector-plugin]）需要有个`conf/conf.default.yaml`配置，`exporter-supervisor.py`在启动的时候会去读该配置，里面必须有如下配置：
```yaml
# exporter进程的keyword，支持"java|xxx|xx"的正则，程序会根据egrep的方式去过滤
exporter_keyword: "kafka_exporter"

# exporter启动的端口范围
port_range: [20000, 60000]

# exporter的启动脚本模板，{xx}的变量将被替换
# 替换的逻辑是将实例的所有字段作为上下文，并且将exporter这个结构体平铺出来，加上`exporter_`的前缀，比如`exporter_host`、`exporter_port`、`exporter_uri`。如果想要增加额外字段，可在CMDB模型里面增加，他会自动放到上下文中，可给到该模板使用
# 注意：目前没有对危险命令做检查，故加其他字段到时候要特别注意
start_cmd_template: "bash ./bin/start.sh --kafka-server {ip}:{port} --exporter-port {exporter_port}"

# 监控实例的过滤条件，只对满足该条件的实例进行守护。语法就是cmdb的search的query条件
cmdb_query:
  isMonitor: true

```
_注意：同时支持`conf/conf.yaml`作为用户自定义配置，最终程序会将两个配置文件合并起来，以`conf/conf.yaml`为优先_



4. 对监控模型的要求
  因为该脚本会直接读取cmdb实例，并根据一定的规则去分配exporter的启动参数并保存在实例数据里面，故这里会对监控模型有要求：
  * 必须有exporter结构体（单结构体），包含如下字段：

    | 字段名 | 类型 | 描述 |
    | - | - | - |
    | protocol | enum | http或https |
    | host | string | exporter所在机器IP |
    | port | number | exporter监听端口 |
    | uri | string | exporter的metrics uri，一般为/metrics |
    | pid | number | exporter启动pid |
    | startCommand | string | 采集插件包的启动命令 |

  * 可选有isMonitor字段，bool型
    用来做是否监控的开关，默认在插件包的`conf.default.yaml`都会有cmdb_query去过滤isMonitor=true的实例
  
  * 建议所有模型都继承自`_BASE_SERVICE_NODE`，该模型都已经具备如上所述字段
  
  


[kafka-collector-plugin]: https://github.com/easy-monitor/kafka-collector-plugin