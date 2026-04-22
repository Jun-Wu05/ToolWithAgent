# 公共工具函数
import os
import logging
import yaml

# 设置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def load_config(config_path):
    """
    加载配置文件
    :param config_path: 配置文件路径
    :return: 配置内容
    """
    if not os.path.exists(config_path):
        logging.error(f'配置文件未找到: {config_path}')
        raise FileNotFoundError(f'{config_path} 不存在')

    with open(config_path, 'r', encoding='utf-8') as config_file:
        return yaml.safe_load(config_file)


# 其他通用工具函数...
