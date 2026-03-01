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
DB_FILE = "cpc_database.json"

try:
    from cpc_dict import FULL_SYNONYM_DICT

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
        """ 意图路由：确定核心技术领域 """
        if not self.client: return []
        print(f"🧠 [AI] 正在分析核心领域: '{user_query}' ...")

        prompt = f"""
        用户输入: "{user_query}"
        请从下方列表中选出 1-3 个最相关的技术领域标签。
        列表: {json.dumps(CANDIDATE_KEYS, ensure_ascii=False)}
        只输出JSON列表，例如 ["标签A", "标签B"]。
        """
        try:
            resp = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            content = resp.choices[0].message.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()
            tags = json.loads(content)
            if isinstance(tags, list):
                valid = [t for t in tags if t in CANDIDATE_KEYS]
                print(f"🎯 [AI] 锁定领域: {valid}")
                return valid
            return []
        except:
            return []

    def expand_keywords(self, user_query):
        """
        🌟 关键词裂变 (仿照查询例子.md Step 1)
        """
        if not self.client: return [user_query]
        print(f"🧠 [AI] 正在扩展关键词 (Synonym Expansion) ...")

        prompt = f"""
        作为一个专利检索专家，请对查询词 "{user_query}" 进行同义词和相关词扩展。

        要求：
        1. 包含专业术语、缩写、下位概念。
        2. 例如输入"WiFi定位"，应扩展为 ["室内定位", "无线局域网定位", "WLAN定位", "无线电定位", "指纹定位"]。
        3. 只返回一个包含 5-8 个词的 JSON 字符串列表。
        """
        try:
            resp = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            content = resp.choices[0].message.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()
            keywords = json.loads(content)
            if isinstance(keywords, list):
                if user_query not in keywords:
                    keywords.insert(0, user_query)
                print(f"✨ [AI] 关键词扩展: {keywords}")
                return keywords
            return [user_query]
        except Exception as e:
            print(f"⚠️ 扩词失败: {e}")
            return [user_query]

    def translate(self, text, code):
        """ 翻译 """
        if not text: return "无描述"
        if text in self.trans_cache: return self.trans_cache[text]
        if not self.client: return text

        prompt = f"""
        Translate the CPC title to concise Chinese.
        Original: "{text}"
        Code: "{code}"
        Only output Chinese. No punctuation.
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

    def _get_node_info(self, code):
        raw = self.details.get(code, {})
        if isinstance(raw, dict):
            return raw.get('title', 'Unknown'), raw.get('def', '')
        elif isinstance(raw, str):
            return raw, ""
        return "Unknown", ""

    def search(self, query):
        scores = Counter()
        matched_dict_codes = []

        # 1. 意图路由
        ai_keys = self.brain.route(query)
        if ai_keys:
            for key in ai_keys:
                codes = FULL_SYNONYM_DICT.get(key, [])
                matched_dict_codes.extend(codes)

        # 2. 关键词扩展
        expanded_keywords = self.brain.expand_keywords(query)
        jieba_words = [w for w in jieba.cut(query) if len(w) >= 2]
        final_keywords = list(set(expanded_keywords + jieba_words))

        # 打印检索报告
        print("\n" + "=" * 50)
        print("📊 检索策略报告")
        print(f"   🔹 核心分类号: {matched_dict_codes if matched_dict_codes else '全库扫描'}")
        print(f"   🔹 检索关键词: {final_keywords}")
        print("=" * 50 + "\n")

        # 3. 执行检索
        # A. 核心领域加权
        if matched_dict_codes:
            for anchor in matched_dict_codes:
                family = self.family_tree.get(anchor, [])
                if not family:
                    for db_code in self.details.keys():
                        if db_code.startswith(anchor): family.append(db_code)
                for code in family:
                    scores[code] += 5000

                    # B. 关键词倒排检索
        candidates = set()
        for kw in final_keywords:
            if kw in self.index: candidates.update(self.index[kw])

        for code in candidates:
            title, _ = self._get_node_info(code)
            score = 0
            for kw in final_keywords:
                if kw in title: score += 50
            if score > 0: scores[code] += score

        return scores.most_common(100)

    # ==========================================================================
    # 🌟 可视化 (V10.0 高精简版逻辑)
    # ==========================================================================
    def visualize_chinese(self, query, results):
        if not results:
            print("❌ 无结果")
            return

        top_code = results[0][0]
        root_code = top_code[:4]
        root_en, _ = self._get_node_info(root_code)
        root_zh = self.brain.translate(root_en, root_code)

        print(f"🚀 生成图谱 | 核心领域: {root_code} ({root_zh})")

        nodes_list = []
        TOP_LIMIT = 40

        for code, score in results:
            if code == root_code: continue
            if code.startswith(root_code):
                nodes_list.append({"code": code, "type": "core", "score": score})
            else:
                nodes_list.append({"code": code, "type": "cross", "score": score})

        nodes_list.sort(key=lambda x: x['score'], reverse=True)
        final_nodes = nodes_list[:TOP_LIMIT]

        print(f"⏳ 正在翻译 Top {len(final_nodes)} 节点...")

        net = Network(height="95vh", width="100%", bgcolor="#f8f9fa", font_color="#333333", select_menu=True)

        net.add_node(root_code, label=f"[核心]\n{root_code}\n{root_zh[:6]}",
                     title=f"【核心领域】\n{root_zh}\n{root_en}",
                     color={'background': '#004085', 'border': '#002752'},
                     size=50, shape='box', font={'color': 'white', 'size': 24})

        for i, item in enumerate(final_nodes):
            code = item['code']
            ntype = item['type']

            en_title, en_def = self._get_node_info(code)
            if i % 5 == 0: print(f"    [{i + 1}/{len(final_nodes)}] 🌐 翻译: {code} ...")

            zh_title = self.brain.translate(en_title, code)

            if ntype == 'core':
                prefix = "[子类]"
                color = '#dc3545'
                shape = 'box'
                edge_dash = False
                size = 30
            elif ntype == 'cross':
                prefix = "[旁系]"
                color = '#fd7e14'
                shape = 'diamond'
                edge_dash = True
                size = 25

            display_title = zh_title[:8] + ".." if len(zh_title) > 8 else zh_title
            label_final = f"{prefix}\n{code}\n{display_title}"

            hover_text = (
                f"【类型】: {prefix}\n"
                f"【代码】: {code}\n"
                f"【中文】: {zh_title}\n"
                f"------------------\n"
                f"【原文】: {en_title}\n"
                f"【定义】: {en_def[:200]}..."
            )

            net.add_node(code, label=label_final, title=hover_text,
                         color={'background': color, 'border': color},
                         shape=shape, size=size, font={'color': 'white'})
            net.add_edge(root_code, code, width=2, color=color, dashes=edge_dash)

        json_options = """
        {
            "layout": {
                "hierarchical": {
                    "enabled": true,
                    "direction": "UD",
                    "sortMethod": "directed",
                    "levelSeparation": 220,
                    "nodeSpacing": 180,
                    "treeSpacing": 200,
                    "blockShifting": true,
                    "edgeMinimization": true,
                    "parentCentralization": true
                }
            },
            "physics": { "enabled": false },
            "edges": {
                "smooth": { "type": "cubicBezier", "forceDirection": "vertical", "roundness": 0.6 },
                "color": { "inherit": "from" }
            },
            "nodes": {
                "font": { "face": "Microsoft YaHei", "multi": true, "vadjust": -5 },
                "shadow": { "enabled": true }
            },
            "interaction": { "hover": true, "dragNodes": false, "zoomView": true }
        }
        """
        net.set_options(json_options)

        output_file = "cpc_report_graph.html"
        net.save_graph(output_file)
        print(f"✅ 图谱生成完毕: {output_file}")
        try:
            webbrowser.open(output_file)
        except:
            pass


if __name__ == "__main__":
    engine = CPCSearchEngine()
    if engine.load_db():
        print("\n🤖 CPC 工业级增强版 (V11.0)")
        while True:
            try:
                q = input("\n👉 请输入 (q退出): ").strip()
                if q in ['q', 'exit']: break
                if not q: continue
                res = engine.search(q)
                engine.visualize_chinese(q, res)
            except KeyboardInterrupt:
                break