#! /usr/local/easyops/python/bin/python
# -*- coding: UTF-8 -*-

import sys
import os
import requests
import random
import signal
import copy
import subprocess
import time
import logging
import traceback
import ConfigParser
import yaml

# CMDB配置，现场根据情况修改
ORG = "8888"
# CMDB用户，一般不需要改
USER = "defaultUser"
# CMDB地址，现场根据情况修改
CMDB_HOST = "http://192.168.100.210:30079"
# 守护间隔，如：每隔3s则去同步cmdb的实例和exporter的进程状态
INTERVAL = 3
# 启动脚本路径，用来判断是否在正确的路径启动，一般不需要改
START_SCRIPT_PATH = './deploy/start_script.sh'

def init_logger(object_id):
    logger = logging.getLogger(object_id)
    logger_folder = 'log'
    if not os.path.isdir(logger_folder):
        os.makedirs(logger_folder, mode=0o755)
    log_file = os.path.join(logger_folder, '%s.log' %object_id)
    hdlr = logging.FileHandler(log_file)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    hdlr.setFormatter(formatter)
    logger.addHandler(hdlr) 
    logger.setLevel(logging.INFO)
    return logger

def get_agent_ip():
    agent_filepath = "/usr/local/easyops/agent/conf/sysconf.ini"
    config = ConfigParser.ConfigParser()
    config.read(agent_filepath)
    return config.get("sys", "local_ip", None)

def search_instances(object_id, query={}, fields={}, page=1, page_size=20, timeout=30):
    resp = requests.post(
        "%s/object/%s/instance/_search" %(CMDB_HOST, object_id),
        headers = {
            "org": ORG,
            "user": USER
        },
        json = {
            "query": query,
            "page": page,
            "page_size": page_size,
            "fields": fields
        },
        timeout = timeout
    )
    if resp.status_code != 200:
        raise ValueError(u"search instances error: %s" %resp.text)
    return resp.json()

def batch_update_instances(object_id, keys, datas, timeout=30):
    resp = requests.post(
        "%s/object/%s/instance/_import" %(CMDB_HOST, object_id),
        headers = {
            "org": ORG,
            "user": USER
        },
        json = {
            "keys": keys,
            "datas": datas
        },
        timeout = timeout
    )
    if resp.status_code != 200:
        raise ValueError(u"batch update instances error: %s" %resp.text)
    return resp.json()


def get_all_nodes(object_id):
    res = search_instances(
        object_id, 
        fields = {"exporter": 1, "instanceId": 1, "ip": 1, "port": 1}
    )
    return res['data']['list']

def create_or_update_exporter_config_by_node(instanceData, assigned_ports, agent_ip, config):
    exporter = instanceData.get('exporter', {
        "protocol": "http",
        "uri": "/metrics",
        "host": agent_ip,
        "pid": None
    })
    # 之前没启动过，或者现在有新的监控机来接管
    if exporter.get('pid') is None or exporter['host'] != agent_ip:
        exporter['host'] = agent_ip
        exporter['port'] = assign_exporter_port(instanceData, assigned_ports, config['port_range'])
        context = copy.deepcopy(instanceData)
        for key,val in exporter.iteritems():
            if key == "pid":
                continue
            context['exporter_%s' %(key)] = val
        exporter['startCommand'] = config['start_cmd_template'].format(**context)
        exporter['pid'] = None
    return exporter

def assign_exporter_port(node, assigned_ports, port_range):
    port = 0
    while 1:
        port = random.randrange(port_range[0], port_range[1])
        if port not in assigned_ports:
            break
    return port

def run_command(cmd, shell=True):
    return subprocess.check_output(cmd, shell=shell)

def get_current_exporter_pids(exporter_keyword):
    cmd = "ps -elf |egrep \"%s\" |grep -v grep |awk '{print $4}'" %(exporter_keyword)
    logger.debug(cmd)
    try:
        output = run_command(cmd)
        pids = [int(pid) for pid in output.strip().split('\n') if pid]
        logger.info('current %s pids: %s' %(exporter_keyword, pids))
        return pids
    except Exception,e:
        logger.error(traceback.format_exc())
        logger.error('did not found current pids, exit')
        raise e

def start_exporter(exporter_inst, instanceData):
    instanceFlag = '%s(%s:%s)' %(instanceData["_object_id"], instanceData["ip"], instanceData["port"])
    cmd = exporter_inst['startCommand']
    if not cmd:
        logger.error("%s not found startCommand" %instanceFlag)
        return None
    logger.info('will start %s with command: %s' %(instanceFlag, cmd))
    try:
        output = run_command(cmd)
        # 拿最后一行作为pid
        pid = output.strip().split('\n')[-1]
        if pid.isdigit():
            # 再次判断下进程是否存活
            if is_pid_alive(pid):
                logger.info('%s success, pid is: %s' %(instanceFlag, pid))
                return int(pid)
        logger.error('%s failed' %(instanceFlag))
    except:
        logger.error(traceback.format_exc())
    return None
    

def is_pid_alive(pid):
    return os.path.isdir('/proc/{}'.format(pid))

def stop_process_by_pids(pids):
    logger.info('will kill pids: %s' %(pids))
    max_retry = 3
    i = 0
    while i < max_retry:
        for pid in pids:
            if is_pid_alive(pid):
                os.kill(int(pid), signal.SIGTERM)
        i += 1
        time.sleep(1)
            

def update_nodes(object_id, nodes):
    res = batch_update_instances(
        object_id, 
        ["instanceId"], 
        [{"instanceId": item["instanceId"], "exporter": item["exporter"]} for item in nodes]
    )

def get_should_stop_pids(current_exporter_pids, all_nodes):
    all_assign_pids = {node['exporter']['pid'] for node in all_nodes if node.get('exporter')}
    should_stop_pids = []
    for pid in current_exporter_pids:
        if pid not in all_assign_pids:
            should_stop_pids.append(pid)
    return should_stop_pids

def main(object_id, config):
    agent_ip = get_agent_ip()
    if not agent_ip:
        logger.error('not found agent ip, exit')
        return
    # 找到所有的服务节点
    all_nodes = get_all_nodes(object_id)
    assigned_ports = {node['exporter']['port'] for node in all_nodes if node.get('exporter')}
    # 通过ps关键字找到当前运行的exporter
    current_exporter_pids = get_current_exporter_pids(config['exporter_keyword'])
    will_update_nodes = []
    for node in all_nodes:
        # 根据node的配置生成exporter_inst
        exporter_inst = create_or_update_exporter_config_by_node(node, assigned_ports, agent_ip, config)
        # pid为空表示新建，pid不为空则表示之前的进程
        if exporter_inst['pid'] is None or exporter_inst['pid'] not in current_exporter_pids:
            pid = start_exporter(exporter_inst, node)
            # 启动成功，则返回pid，否则返回None
            if pid: 
                exporter_inst['pid'] = pid
                node['exporter'] = exporter_inst
                will_update_nodes.append(node)
            # 随机sleep几秒，避免机器负载太高
            time.sleep(random.randrange(0,2))
    # 更新CMDB数据
    if will_update_nodes:
        update_nodes(object_id, will_update_nodes)
    # 通过比对stop掉已经不需要启动的exporter
    should_stop_pids = get_should_stop_pids(current_exporter_pids, all_nodes)
    if should_stop_pids:
        stop_process_by_pids(should_stop_pids)

def load_config(config_path):
    try:
        with open(config_path) as fp:
            config = yaml.load(fp)
            logger.info('load config: %s' %config)
            return config
    except:
        raise ValueError("%s parse error, it is not a valid yaml file" %config_path)
        sys.exit(1)

if __name__ == '__main__':
    args = sys.argv
    if len(args) != 3:
        print "Usage: %s [objectId] [confpath], eg: %s KAFKA_SERVICE_NODE ./conf/conf.default.yaml" %(args[0], args[0])
        sys.exit(1)
    if not os.path.isfile(args[2]):
        print "not found %s, you should run at plugin root folder" %(args[2])
        sys.exit(2)
    logger = init_logger(args[1])
    config = load_config(args[2])
    if not os.path.isfile(START_SCRIPT_PATH):
        print "not found %s, may be you not run at plugin root folder" %(START_SCRIPT_PATH)
        sys.exit(2)
    print '%s start' %args[1]
    while 1:
        try:
            while 1:
                logger.info('start...')
                main(args[1], config)
                logger.info('end...')
                time.sleep(INTERVAL)
        except (KeyboardInterrupt,SystemExit),e:
            sys.exit(1)
        except Exception,e:
            logger.error(traceback.format_exc())
            time.sleep(INTERVAL)

