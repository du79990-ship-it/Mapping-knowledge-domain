import xml.etree.ElementTree as ET
import sqlite3
import re
import os

# =================配置区=================
XML_FILE_PATH = "FR_ipc_scheme_20260101.xml"
DB_FILE_PATH = "ipc_master.db"


# =======================================

def init_db():
    """初始化 SQLite 数据库"""
    print("⚙️ 正在初始化数据库...")
    if os.path.exists(DB_FILE_PATH):
        os.remove(DB_FILE_PATH)  # 为了演示，每次重建

    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    # 创建两张表：主表和全文索引表(FTS)
    cursor.execute('''
        CREATE TABLE ipc_raw (
            symbol TEXT PRIMARY KEY,
            level TEXT,
            title TEXT
        )
    ''')
    # 创建 FTS5 全文搜索表 (大幅提升搜索速度)
    cursor.execute('''
        CREATE VIRTUAL TABLE ipc_search USING fts5(symbol, title)
    ''')
    conn.commit()
    return conn


def parse_wipo_xml_and_import(xml_path, conn):
    """
    解析 WIPO 官方 XML 格式 (简化版逻辑)
    注意：WIPO XML 结构很深，这里演示核心提取逻辑
    """
    print(f"📂 正在读取 XML 文件: {xml_path} (这可能需要几分钟)...")

    cursor = conn.cursor()
    count = 0

    # --- 模拟：如果没有真实文件，我们生成一些模拟数据来演示流程 ---
    if not os.path.exists(xml_path):
        print("⚠️ 未找到 XML 文件，正在生成模拟数据演示入库流程...")
        mock_data = [
            ("A41F 3/00", "Main Group", "Braces for trousers"),
            ("B64F 1/02", "Subgroup", "Arresting gear; Liquid barriers; Catapults"),
            ("H04N 7/18", "Subgroup", "Closed-circuit television [CCTV] systems"),
            ("H04N 9/00", "Main Group", "Details of colour television systems"),
            ("H04N 9/64", "Subgroup", "Circuits for processing colour signals"),
            ("H04N 21/00", "Main Group", "Selective content distribution, e.g. video-on-demand [VOD]"),
            (
            "G01S 5/00", "Main Group", "Position-fixing by co-ordinating two or more direction-finding determinations"),
        ]

        for symbol, level, title in mock_data:
            # 插入原始数据
            cursor.execute("INSERT INTO ipc_raw VALUES (?,?,?)", (symbol, level, title))
            # 插入搜索引擎
            cursor.execute("INSERT INTO ipc_search VALUES (?,?)", (symbol, title))
            count += 1

    else:
        # --- 真实 XML 解析逻辑 (基于 WIPO 标准) ---
        # 这是一个流式解析器，防止内存溢出
        context = ET.iterparse(xml_path, events=('end',))

        for event, elem in context:
            # WIPO XML 中，<ipcEntry> 代表一个条目
            if elem.tag.endswith('ipcEntry'):
                symbol = elem.attrib.get('symbol', '')
                kind = elem.attrib.get('kind', '')  # c=class, u=subclass, g=group

                # 提取标题文本 (通常在 textBody 下)
                title_parts = []
                for text_tag in elem.iter():
                    if text_tag.tag.endswith('text') and text_tag.text:
                        title_parts.append(text_tag.text.strip())

                full_title = " ".join(title_parts)

                # 清洗 Symbol (WIPO 的 Symbol 格式可能是 H04N0007180000，需要转为 H04N 7/18)
                # 这里做个简单的格式化演示
                readable_symbol = format_ipc_symbol(symbol)

                if readable_symbol and full_title:
                    try:
                        cursor.execute("INSERT INTO ipc_raw VALUES (?,?,?)", (readable_symbol, kind, full_title))
                        cursor.execute("INSERT INTO ipc_search VALUES (?,?)", (readable_symbol, full_title))
                        count += 1
                    except:
                        pass  # 跳过重复

                # 清理内存
                elem.clear()

            if count % 1000 == 0:
                print(f"   -> 已导入 {count} 条...", end='\r')

    conn.commit()
    print(f"\n✅ 入库完成！共导入 {count} 条数据。")


def format_ipc_symbol(raw_symbol):
    """
    将数据库原始长码转为人类可读格式
    例如: H04N0007180000 -> H04N 7/18
    (实际转换规则比较复杂，这里仅作示意)
    """
    return raw_symbol  # 实际项目中需要编写正则处理


if __name__ == "__main__":
    # 1. 初始化
    conn = init_db()

    # 2. 导入数据 (ETL)
    parse_wipo_xml_and_import(XML_FILE_PATH, conn)

    # 3. 测试查询
    print("-" * 30)
    test_query = "video"
    print(f"🔎 测试数据库查询: '{test_query}'")
    cursor = conn.cursor()

    # 使用 FTS5 全文搜索语法
    cursor.execute("SELECT symbol, title FROM ipc_search WHERE title MATCH ? LIMIT 5", (test_query,))
    results = cursor.fetchall()

    for row in results:
        print(f"   [Found] {row[0]}: {row[1]}")

    conn.close()