import yaml

def load_config(config_path: str):
	with open(config_path) as f:
		return yaml.safe_load(f)

def process_phase1(input_dir: str, output_dir: str) -> dict:
	config = load_config('config.yaml')
	input_dir = config['phase1']['input_dir']
	output_dir = config['phase1']['output_dir']
	"""
	 # 执行 Phase1 处理
		# 执行 Phase1 处理
		# 执行 Phase1 处理
  """
def decode_base64_text(base64_string: str) -> str:
	import base64
	return base64.b64decode(base64_string).decode('utf-8')

def extract_normalize_indexes(log: str) -> List[float]:
	import re
	indexes = re.findall(r'\d+', log)
	return [float(idx) for idx in indexes]

def _extract_indexes_from_obj(obj: Dict[str, Any]) -> float:
	return float(obj['index'])  # Example extraction

def _extract_original_log_result() -> Any:
	return {...}

def process_phase1(input_dir: str, output_dir: str) -> dict:

	# 执行Phase1处理

	# Function logic goes here
	return {
		'normalize_indexes_file': output_dir + '\normalize_indexes.txt',
		'decoded_files': [],
		'stats': {'total_files': 0, 'success': 0, 'failed': 0},
	}
