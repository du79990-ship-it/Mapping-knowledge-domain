import json
import os
import re
import jieba
import webbrowser
import time
from collections import defaultdict, Counter
from pyvis.network import Network

# --- 1. 引入 OpenAI SDK ---
try:
    from openai import OpenAI
except ImportError:
    print("❌ 请先安装依赖: pip install openai pyvis")
    exit()

# ==============================================================================
# ⚙️ 配置区域
# ==============================================================================
# ⚠️⚠️⚠️ 请在此处填入您的阿里云 API Key ⚠️⚠️⚠️
DASHSCOPE_API_KEY = "sk-569d9c8b329c48038af583b0ce6bc5f2"

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen-plus"

# ==============================================================================
# 📚 资源加载
# ==============================================================================
DB_FILE = "ipc_massive.json"

try:
    from ipc_dict import FULL_SYNONYM_DICT

    CANDIDATE_KEYS = list(FULL_SYNONYM_DICT.keys())
except ImportError:
    CANDIDATE_KEYS = []
    FULL_SYNONYM_DICT = {}


# ==============================================================================
# 🧠 AI 核心类
# ==============================================================================
class QwenBrain:
    def __init__(self):
        if "sk-xxx" in DASHSCOPE_API_KEY:
            self.client = None
        else:
            self.client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=BASE_URL)
        self.trans_cache = {}

    def route(self, user_query):
        if not self.client: return None
        print(f"🧠 [AI] 正在分析意图: '{user_query}' ...")
        prompt = f"""
        用户输入: "{user_query}"
        请从下方列表中选出最匹配的分类词。只输出词本身，若无匹配输出 "None"。
        列表: {json.dumps(CANDIDATE_KEYS, ensure_ascii=False)}
        """
        try:
            resp = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.01
            )
            return resp.choices[0].message.content.strip().replace('"', '').replace("'", "")
        except:
            return None

    def translate(self, text, code):
        if not text: return "无描述"
        if text in self.trans_cache: return self.trans_cache[text]
        if not self.client: return text

        prompt = f"""
        Translate the following Patent Classification (CPC) title into concise Chinese.
        Original: "{text}"
        Code: "{code}"
        Requirement: Only output the Chinese translation. No explanations.
        Example: "Vehicles" -> "车辆"
        """
        try:
            resp = self.client.chat.completions.create(
                model="qwen-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            zh_text = resp.choices[0].message.content.strip()
            self.trans_cache[text] = zh_text
            return zh_text
        except:
            return text


# ==============================================================================
# 🔍 核心检索引擎
# ==============================================================================
class CPCSearchEngine:
    def __init__(self):
        self.brain = QwenBrain()
        self.details = {}
        self.index = {}
        self.family_tree = defaultdict(list)

    def load_db(self):
        if not os.path.exists(DB_FILE):
            print(f"❌ 找不到 {DB_FILE}")
            return False
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.details = data["details"]
            self.index = data["index"]
            if "family_tree" in data:
                self.family_tree = data["family_tree"]
            else:
                for code in self.details.keys():
                    if len(code) >= 4:
                        self.family_tree[code[:4]].append(code)
        print(f"✅ 引擎就绪 (加载 {len(self.details)} 节点)")
        return True

    # 🌟 新增：数据清洗助手函数 (修复 AttributeError 的关键)
    def _get_node_info(self, code):
        """ 安全地获取节点信息，兼容字典和字符串格式 """
        raw_data = self.details.get(code, {})

        if isinstance(raw_data, dict):
            # 标准格式
            title = raw_data.get('title', 'Unknown Title')
            definition = raw_data.get('def', '')
        elif isinstance(raw_data, str):
            # 兼容格式：只有标题字符串
            title = raw_data
            definition = ""
        else:
            # 异常情况
            title = "Unknown"
            definition = ""

        return title, definition

    def search(self, query):
        scores = Counter()
        matched_codes = []

        ai_key = self.brain.route(query)
        if ai_key and ai_key in FULL_SYNONYM_DICT:
            matched_codes = FULL_SYNONYM_DICT[ai_key]
            print(f"🎯 命中领域: {ai_key} -> {matched_codes}")

        if matched_codes:
            for anchor in matched_codes:
                family = self.family_tree.get(anchor, [])
                if not family:
                    for db_code in self.details.keys():
                        if db_code.startswith(anchor): family.append(db_code)
                for code in family:
                    scores[code] += 5000

        keywords = [w for w in jieba.cut(query) if len(w) >= 2]
        if ai_key: keywords.append(ai_key)

        candidates = set()
        for kw in keywords:
            if kw in self.index: candidates.update(self.index[kw])

        for code in candidates:
            # 使用新的安全获取方法
            title, definition = self._get_node_info(code)
            score = 0
            for kw in keywords:
                if kw in title: score += 50
            if score > 0: scores[code] += score

        return scores.most_common(100)

    # ==========================================================================
    # 🌟 全量翻译 + 直角结构图谱 (修复崩溃版)
    # ==========================================================================
    def visualize_chinese(self, query, results):
        if not results:
            print("❌ 无结果")
            return

        top_code = results[0][0]
        root_code = top_code[:4]

        # 1. 翻译 Root (使用安全方法获取)
        root_en_title, _ = self._get_node_info(root_code)
        root_zh_title = self.brain.translate(root_en_title, root_code)

        print(f"🚀 生成全量中文图谱 | 核心: {root_code} ({root_zh_title})")

        cores, sides = [], []
        result_map = dict(results)
        family = self.family_tree.get(root_code, [])

        display_nodes = []

        for code in family:
            if code == root_code: continue
            if code in result_map:
                display_nodes.append({"code": code, "type": "core", "score": result_map[code]})
            else:
                display_nodes.append({"code": code, "type": "side", "score": 0})

        for code, score in results:
            if not code.startswith(root_code):
                display_nodes.append({"code": code, "type": "cross", "score": score})

        display_nodes.sort(key=lambda x: x['score'], reverse=True)
        final_nodes = display_nodes[:60]
        total_nodes = len(final_nodes)

        print(f"⏳ 正在全量翻译 {total_nodes} 个节点，请耐心等待...")

        for i, item in enumerate(final_nodes):
            code = item['code']
            # 使用安全方法获取
            en_title, en_def = self._get_node_info(code)
            en_def_short = en_def[:300]

            print(f"    [{i + 1}/{total_nodes}] 🌐 翻译: {code} ...")

            zh_title = self.brain.translate(en_title, code)

            if len(zh_title) > 10:
                label_text = f"{code}\n{zh_title[:10]}.."
            else:
                label_text = f"{code}\n{zh_title}"

            hover_text = (
                f"【代码】: {code}\n"
                f"【中文】: {zh_title}\n"
                f"----------------------\n"
                f"【原文】: {en_title}\n"
                f"【定义】: {en_def_short}..."
            )

            node = {
                "id": code,
                "label": label_text,
                "title": hover_text,
                "type": item['type']
            }

            if item['type'] == 'core':
                cores.append(node)
            elif item['type'] == 'cross':
                cores.append(node)
            else:
                sides.append(node)

        net = Network(height="95vh", width="100%", bgcolor="#f7f9ff", font_color="#333333", select_menu=True)

        net.add_node(root_code, label=f"ROOT\n{root_code}\n{root_zh_title[:8]}",
                     title=f"核心大类: {root_zh_title}\n{root_en_title}",
                     color={'background': '#004085', 'border': '#002752'},
                     size=50, shape='box', font={'color': 'white', 'size': 20})

        for c in cores:
            color_bg = '#dc3545' if c['type'] == 'core' else '#fd7e14'
            net.add_node(c['id'], label=c['label'], title=c['title'],
                         color={'background': color_bg, 'border': color_bg},
                         size=30, shape='box', font={'color': 'white'})
            net.add_edge(root_code, c['id'], width=3, color=color_bg, arrows='to')

        for s in sides:
            net.add_node(s['id'], label=s['label'], title=s['title'],
                         color={'background': '#e9ecef', 'border': '#adb5bd'},
                         size=20, shape='box', font={'color': '#495057'})
            net.add_edge(root_code, s['id'], width=1, color='#ced4da', arrows='to')

        json_options = """
        {
            "layout": {
                "hierarchical": {
                    "enabled": true,
                    "direction": "UD",
                    "sortMethod": "directed",
                    "levelSeparation": 200,
                    "nodeSpacing": 200,
                    "treeSpacing": 220,
                    "blockShifting": true,
                    "edgeMinimization": true,
                    "parentCentralization": true
                }
            },
            "physics": {
                "enabled": false
            },
            "edges": {
                "smooth": {
                    "type": "cubicBezier",
                    "forceDirection": "vertical",
                    "roundness": 0.5
                },
                "color": { "inherit": "from" }
            },
            "nodes": {
                "font": { "face": "Microsoft YaHei", "multi": true },
                "shadow": { "enabled": true }
            },
            "interaction": {
                "hover": true,
                "dragNodes": false,
                "zoomView": true
            }
        }
        """
        net.set_options(json_options)

        output_file = "ipc_full_chinese_graph.html"
        net.save_graph(output_file)
        print(f"✅ 全量中文图谱已生成: {output_file}")
        try:
            webbrowser.open(output_file)
        except:
            pass


if __name__ == "__main__":
    engine = CPCSearchEngine()
    if engine.load_db():
        print("\n🤖 IPC 全量中文图谱系统 (V6.2 Final)")
        while True:
            try:
                q = input("\n👉 请输入 (q退出): ").strip()
                if q in ['q', 'exit']: break
                if not q: continue
                res = engine.search(q)
                engine.visualize_chinese(q, res)
            except KeyboardInterrupt:
                break