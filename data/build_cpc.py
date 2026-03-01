import pdfplumber
import os
import re
import json
import jieba
import time
from collections import defaultdict

# ==============================================================================
# 🏗️ CPC 知识库构建器 (V7.0 父类捕获版)
# 核心修复:
# 1. 遇到大类(A01B)时，立刻将其存入数据库，不再只存子类
# 2. 增强对标题的清洗能力
# ==============================================================================

SCHEME_FOLDER = "CPC-scheme"
DEF_FOLDER = "CPC-definition"
OUTPUT_FILE = "cpc_database.json"

STOP_WORDS = {
    "的", "了", "和", "或", "在", "与", "及", "对于", "关于", "一种", "所述",
    "及其", "装置", "方法", "系统", "设备", "用于", "特征", "在于", "包括",
    "进行", "使用", "制造", "处理", "应用", "组合", "至少", "一个", "部分",
    "参见", "例如", "即", "如下", "参考", "定义", "分类", "covered", "by", "see"
}


def clean_text(text):
    """ 清洗文本 (修复了之前的语法错误) """
    if not text: return ""

    # 1. 去除 标记
    #text = re.sub(r '\', text)

    # 2. 核心修复: 使用 replace 删除特殊符号 (避免正则反斜杠报错)
    # 针对您的文件格式: "$2/10$","description"
    text = text.replace('\\', '')  # 删除反斜杠
    text = text.replace('"', ' ')  # 删除引号
    text = text.replace('$', ' ')  # 删除美元符
    text = text.replace(',', ' ')  # 删除CSV逗号

    # 3. 压缩空格
    return re.sub(r'\s+', ' ', text).strip()


def extract_tokens(text):
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
    words = jieba.cut(text)
    return [w for w in words if len(w) >= 2 and w.lower() not in STOP_WORDS]


def build_cpc_database():
    print("🚀 启动 CPC 构建引擎 (V7.1 CSV适配版)...")

    # 自动适配文件夹名
    global SCHEME_FOLDER
    if not os.path.exists(SCHEME_FOLDER) and os.path.exists("CPC-scheme"):
        SCHEME_FOLDER = "CPC-scheme"
        print(f"   -> 自动检测到文件夹: {SCHEME_FOLDER}")

    db_details = {}
    inverted_index = defaultdict(list)
    family_tree = defaultdict(list)

    total_parsed = 0

    print(f"\n📖 [1/2] 扫描 Scheme ({SCHEME_FOLDER})...")

    file_list = []
    for root, dirs, files in os.walk(SCHEME_FOLDER):
        for file in files:
            if file.lower().endswith('.pdf'):
                file_list.append(os.path.join(root, file))

    print(f"   -> 发现 {len(file_list)} 个 PDF 文件")

    # 正则 A: 寻找大类上下文 (如 A01B)
    # 匹配单独一行的 A01B，允许前后有引号
    re_context = re.compile(r'^\s*["\']?([A-HY]\d{2}[A-Z])["\']?\s*$')

    # 正则 B: 寻找分类号 (如 1/00)
    # 您的文件里全是 "$1/00$"，这个正则专门抓中间的数字
    re_code = re.compile(r'(\d{1,4}/\d{2,6})')

    for i, path in enumerate(file_list):
        current_subclass = None

        # 1. 从文件名强制提取上下文 (最稳妥的方式)
        # 例如 cpc-scheme-A01B.pdf -> A01B
        fname_match = re.search(r'([A-HY]\d{2}[A-Z])', os.path.basename(path))
        if fname_match:
            current_subclass = fname_match.group(1)

            # 把大类本身先存进去
            if current_subclass not in db_details:
                db_details[current_subclass] = {
                    "title": f"{current_subclass} General Category",
                    "def": "", "source": "filename"
                }

        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    # 使用 raw text 模式，因为您的文件本质是 CSV 文本流
                    text = page.extract_text() or ""

                    lines = text.split('\n')
                    for line in lines:
                        line = line.strip()
                        if not line: continue

                        # 先做一次粗略清洗，方便正则匹配
                        clean_line_raw = line.replace('"', '').replace('$', '').replace(',', ' ').strip()

                        # --- 逻辑 A: 更新上下文 (如果在正文里发现了 A01B) ---
                        ctx_match = re_context.match(clean_line_raw)
                        if ctx_match:
                            current_subclass = ctx_match.group(1)
                            continue

                        # --- 逻辑 B: 提取数据 ---
                        code_match = re_code.search(clean_line_raw)

                        if code_match and current_subclass:
                            # 提取子号 (如 1/00)
                            sub_code = code_match.group(1)

                            # 排除干扰 (如日期 2026/01)
                            if sub_code.startswith('20') and len(sub_code) >= 6:
                                continue

                            # 组合完整分类号: A01B + 1/00 = A01B 1/00
                            full_code = f"{current_subclass} {sub_code}"

                            # 提取标题:
                            # 原始行: "$1/00$","Hand tools..."
                            # 清洗后: 1/00 Hand tools...
                            # 我们把 1/00 替换掉，剩下的就是标题
                            title = clean_text(line)
                            title = title.replace(sub_code, '').strip()

                            # 去掉开头可能残留的数字或符号
                            title = re.sub(r'^[\d/\-\.]+', '', title).strip()

                            if len(title) < 2: continue

                            # 存入数据库
                            db_details[full_code] = {
                                "title": title,
                                "def": "",
                                "source": "scheme"
                            }

                            # 建立族谱
                            family_tree[current_subclass].append(full_code)

                            # 建立索引
                            for t in extract_tokens(title):
                                if full_code not in inverted_index[t]:
                                    inverted_index[t].append(full_code)

                            total_parsed += 1

            # 进度打印
            if (i + 1) % 50 == 0:
                print(f"   ...进度 {i + 1}/{len(file_list)} | 累计抓取: {total_parsed}")

        except Exception as e:
            print(f"   ❌ 解析错误 {os.path.basename(path)}: {e}")

    print(f"   ✅ Scheme 解析结束: 共 {total_parsed} 个节点")

    # ---------------------------------------------------------
    # 2. 扫描 Definition
    # ---------------------------------------------------------
    print(f"\n📖 [2/2] 扫描 Definition ({DEF_FOLDER})...")

    def_files = []
    if os.path.exists(DEF_FOLDER):
        for root, dirs, files in os.walk(DEF_FOLDER):
            for file in files:
                if file.lower().endswith('.pdf'):
                    def_files.append(os.path.join(root, file))

    for path in def_files:
        match = re.search(r'([A-HY]\d{2}[A-Z])', os.path.basename(path))
        if match:
            target_code = match.group(1)
            if len(target_code) > 4:
                target_code = target_code[:4] + " " + target_code[4:]

            try:
                full_text = ""
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        full_text += (page.extract_text() or "") + " "

                clean_def = clean_text(full_text)

                if target_code in db_details:
                    db_details[target_code]["def"] = clean_def
                else:
                    db_details[target_code] = {
                        "title": "CPC Definition",
                        "def": clean_def,
                        "source": "def_only"
                    }
                    if len(target_code) >= 4:
                        family_tree[target_code[:4]].append(target_code)

                for t in extract_tokens(clean_def):
                    if target_code not in inverted_index[t]:
                        inverted_index[t].append(target_code)
            except:
                pass

    # ---------------------------------------------------------
    # 3. 保存
    # ---------------------------------------------------------
    print("\n💾 保存数据库...")
    data = {
        "details": db_details,
        "index": inverted_index,
        "family_tree": family_tree
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"🎉 构建完成! 数据库节点数: {len(db_details)}")


if __name__ == "__main__":
    build_cpc_database()