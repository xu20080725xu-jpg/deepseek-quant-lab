"""Run locally; paste only the generated hash into Streamlit Secrets."""
from getpass import getpass
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantlab.cloud_access import hash_password

if __name__ == "__main__":
    password = getpass("设置至少16个字符的站主访问口令（不显示、不保存）：")
    confirmation = getpass("再次输入：")
    if password != confirmation:
        raise SystemExit("两次不一致，没有生成配置")
    print('QUANTLAB_PASSWORD_HASH = "' + hash_password(password) + '"')
